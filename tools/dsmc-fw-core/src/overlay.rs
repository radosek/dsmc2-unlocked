//! Monitor overlays (`overlays/*.overlay`): a SQLite database under RED's AES
//! page codec (the `.preset` key), read by `overlay2_if::getOverlay`.
//!
//! Schema (from `overlay2_if::saveOverlay`):
//! `overlay_flags(show_frame_guide, show_action_guide, show_title_guide)`,
//! `overlay_object(object_id, pos, line, col, size, static_text)`, `info(version)`.
//! `pos` is one of six screen zones, `line` the row inside the zone and `col`
//! the overall order. Item names come from the id → name map the firmware
//! builds at static init (`FUN_80b6b14c`, 53 entries).

use crate::sqlite;

/// `object_id` → editor label ("Name (ABBR)").
pub const ITEMS: &[(u32, &str)] = &[
    (0, "Custom Label (LBL)"),
    (1, "Timecode (TC)"),
    (2, "ISO (ISO)"),
    (3, "Sensor Frame Rate (FPS)"),
    (4, "Shutter Speed (SPD)"),
    (5, "Aperture (APTR)"),
    (6, "Color Temperature (C.TMP)"),
    (7, "Video Format (FRMT)"),
    (8, "REDcode (RC)"),
    (9, "Sensor Temperature (STEMP)"),
    (10, "Fan Speed (FAN)"),
    (11, "Power Info (PWR)"),
    (12, "Media Info (MDIA)"),
    (13, "Clip Name (CLIP)"),
    (14, "Scene Take Info (SCN)"),
    (15, "Motion: Gyro Data (GYRO)"),
    (16, "Histogram (HIST)"),
    (17, "Focus Distance (F.DST)"),
    (18, "Focal Length (F.LEN)"),
    (19, "Record Indicator (REC)"),
    (20, "Camera Name (NAME)"),
    (21, "Camera Group (GRP)"),
    (22, "Color Space (C.SP)"),
    (24, "Audio Levels (VU)"),
    (25, "HDR Status (HDR)"),
    (26, "Magnify Status (1:1)"),
    (27, "False Color (FC)"),
    (28, "LAN Status (LAN)"),
    (29, "RIG Status (RIG)"),
    (30, "Timecode Sync Status (TCS)"),
    (31, "Genlock Status (GEN)"),
    (32, "Sync Status (SYNC)"),
    (33, "Project Rate (PR)"),
    (34, "Core Temperature (CTEMP)"),
    (35, "AF/AE Status (ALGO)"),
    (37, "Traffic Lights (TLS)"),
    (38, "Magnify Indicator (MI)"),
    (39, "Motor Module Focus Status (F)"),
    (40, "Motor Module Iris Status (I)"),
    (41, "Motor Module Zoom Status (Z)"),
    (42, "WiFi Module Status (WIFI)"),
    (46, "MOTION MOUNT Info (MM)"),
    (47, "3ality Data (3AD)"),
    (48, "Raw/Log View Mode (RAW)"),
    (50, "Remote Control Panel (RCP)"),
    (51, "Shutter Angle (ANG)"),
    (52, "Exposure (EXP)"),
    (53, "Reduced Judder Preview Mode (RJP)"),
    (54, "Quicktime Status (QT)"),
    (55, "Varispeed Audio Status (V.AUD)"),
    (56, "Camera ID (ID)"),
    (57, "Record Indicator w/o Annotations (REC2)"),
    (58, "Monitor LUT (LUT)"),
];

/// `pos` → screen zone.
pub const ZONES: [&str; 6] = [
    "top left",
    "top center",
    "top right",
    "bottom left",
    "bottom center",
    "bottom right",
];

/// `size` → editor label.
pub const SIZES: [&str; 3] = ["Small", "Normal", "Large"];

#[derive(Debug, Clone, PartialEq)]
pub struct Item {
    pub id: u32,
    /// Editor label, or `None` for an id this firmware does not know.
    pub name: Option<&'static str>,
    pub pos: u32,
    pub line: u32,
    pub col: u32,
    pub size: u32,
    /// The text of a Custom Label (id 0); empty otherwise.
    pub text: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Overlay {
    pub frame_guide: bool,
    pub action_guide: bool,
    pub title_guide: bool,
    pub items: Vec<Item>,
}

pub fn item_name(id: u32) -> Option<&'static str> {
    ITEMS.iter().find(|(i, _)| *i == id).map(|(_, n)| *n)
}

/// Read an `.overlay` file (encrypted or plain SQLite).
pub fn read(data: &[u8]) -> Result<Overlay, String> {
    let tables = sqlite::dump(data, None, None)?;
    let table = |n: &str| tables.iter().find(|t| t.name == n);
    let objects = table("overlay_object").ok_or("not an overlay: no overlay_object table")?;
    let col = |name: &str| {
        objects
            .columns
            .iter()
            .position(|c| c == name)
            .ok_or_else(|| format!("overlay_object has no {name} column"))
    };
    let (ci, cp, cl, cc, cs, ct) = (
        col("object_id")?,
        col("pos")?,
        col("line")?,
        col("col")?,
        col("size")?,
        col("static_text")?,
    );
    let num = |v: &str| v.parse::<u32>().unwrap_or(0);
    let mut items: Vec<Item> = objects
        .rows
        .iter()
        .map(|r| Item {
            id: num(&r[ci]),
            name: item_name(num(&r[ci])),
            pos: num(&r[cp]),
            line: num(&r[cl]),
            col: num(&r[cc]),
            size: num(&r[cs]),
            text: r[ct].clone(),
        })
        .collect();
    items.sort_by_key(|i| (i.pos, i.line, i.col));
    // The firmware shows every guide when the flags table is missing.
    let flag = |i: usize| {
        table("overlay_flags")
            .and_then(|t| t.rows.first())
            .is_none_or(|r| r.get(i).is_some_and(|v| v != "0" && !v.is_empty()))
    };
    Ok(Overlay {
        frame_guide: flag(0),
        action_guide: flag(1),
        title_guide: flag(2),
        items,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn overlay_db(flags: &str, objects: &str) -> Vec<u8> {
        let mut con = rusqlite::Connection::open_in_memory().unwrap();
        con.execute_batch(&format!(
            "CREATE TABLE overlay_flags (show_frame_guide, show_action_guide, show_title_guide);
             CREATE TABLE overlay_object (object_id, pos, line, col, size, static_text TEXT);
             CREATE TABLE info(version); INSERT INTO info values(1);
             {flags} {objects}"
        ))
        .unwrap();
        con.serialize(rusqlite::MAIN_DB).unwrap().to_vec()
    }

    #[test]
    fn reads_items_in_layout_order() {
        let db = overlay_db(
            "INSERT INTO overlay_flags VALUES(1, 0, 1);",
            "INSERT INTO overlay_object VALUES(1, 5, 0, 2, 1, '');
             INSERT INTO overlay_object VALUES(0, 0, 1, 1, 2, 'A CAM');
             INSERT INTO overlay_object VALUES(19, 2, 0, 0, 0, '');
             INSERT INTO overlay_object VALUES(99, 0, 0, 3, 0, '');",
        );
        let o = read(&db).unwrap();
        assert!(o.frame_guide && !o.action_guide && o.title_guide);
        let got: Vec<_> = o
            .items
            .iter()
            .map(|i| (i.id, i.pos, i.line, i.name))
            .collect();
        assert_eq!(
            got,
            [
                (99, 0, 0, None),
                (0, 0, 1, Some("Custom Label (LBL)")),
                (19, 2, 0, Some("Record Indicator (REC)")),
                (1, 5, 0, Some("Timecode (TC)")),
            ]
        );
        assert_eq!(o.items[1].text, "A CAM");
    }

    #[test]
    fn missing_flags_mean_all_guides() {
        let o = read(&overlay_db("", "")).unwrap();
        assert!(o.frame_guide && o.action_guide && o.title_guide);
        assert!(o.items.is_empty());
    }

    #[test]
    fn rejects_non_overlay_db() {
        let pt = crate::preset::build_plaintext_db(7, &[]).unwrap();
        assert!(read(&pt).unwrap_err().contains("overlay_object"));
    }

    #[test]
    fn item_map_matches_firmware_count() {
        assert_eq!(ITEMS.len(), 53);
    }
}
