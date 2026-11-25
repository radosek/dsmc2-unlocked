//! Read-only dump of a SQLite image (e.g. `cdb2/factory.db` from an extracted
//! package): every table with its columns and the first rows, values as text.

use std::borrow::Cow;

use rusqlite::types::ValueRef;

#[derive(Debug)]
pub struct Table {
    pub name: String,
    pub columns: Vec<String>,
    pub rows: Vec<Vec<String>>,
    /// Row count of the whole table; `rows` holds at most the requested limit.
    pub total: u64,
}

fn text(v: ValueRef<'_>) -> String {
    match v {
        ValueRef::Null => String::new(),
        ValueRef::Integer(i) => i.to_string(),
        ValueRef::Real(f) => f.to_string(),
        ValueRef::Text(t) => String::from_utf8_lossy(t).into_owned(),
        ValueRef::Blob(b) => format!("<blob {} bytes>", b.len()),
    }
}

const MAGIC: &[u8] = b"SQLite format 3\0";

/// The plaintext SQLite image of `db`: as-is when it already is one, else
/// decrypted with RED's AES page codec (the one `.preset` and `.overlay` use).
pub fn plaintext(db: &[u8]) -> Result<Cow<'_, [u8]>, String> {
    if db.starts_with(MAGIC) {
        return Ok(Cow::Borrowed(db));
    }
    if db.len() < 1024 || !db.len().is_multiple_of(512) {
        return Err("not a SQLite database".into());
    }
    let pt = crate::preset::decrypt(db);
    if pt.starts_with(MAGIC) {
        Ok(Cow::Owned(pt))
    } else {
        Err("not a SQLite database, and not one under RED's preset key".into())
    }
}

/// Open `db` (plain or RED-encrypted SQLite) and dump each table (or only
/// `only`), up to `row_limit` rows each (`None` = all rows).
pub fn dump(db: &[u8], only: Option<&str>, row_limit: Option<usize>) -> Result<Vec<Table>, String> {
    let db = plaintext(db)?;
    let e = |e: rusqlite::Error| e.to_string();
    let mut con = rusqlite::Connection::open_in_memory().map_err(e)?;
    con.deserialize_read_exact(rusqlite::MAIN_DB, &*db, db.len(), true)
        .map_err(e)?;
    let names: Vec<String> = con
        .prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        .map_err(e)?
        .query_map([], |r| r.get(0))
        .map_err(e)?
        .collect::<Result<_, _>>()
        .map_err(e)?;
    if let Some(t) = only {
        if !names.iter().any(|n| n == t) {
            return Err(format!("no table {t:?}; tables: {}", names.join(", ")));
        }
    }
    let limit = row_limit.map_or(-1, |n| n as i64);
    let mut out = Vec::with_capacity(names.len());
    for name in names.into_iter().filter(|n| only.is_none_or(|t| t == n)) {
        let q = format!("\"{}\"", name.replace('"', "\"\""));
        let total: i64 = con
            .query_row(&format!("SELECT count(*) FROM {q}"), [], |r| r.get(0))
            .map_err(e)?;
        let mut stmt = con
            .prepare(&format!("SELECT * FROM {q} LIMIT {limit}"))
            .map_err(e)?;
        let columns: Vec<String> = stmt.column_names().map(str::to_string).collect();
        let n = columns.len();
        let rows = stmt
            .query_map([], |r| {
                (0..n)
                    .map(|i| r.get_ref(i).map(text))
                    .collect::<Result<Vec<_>, _>>()
            })
            .map_err(e)?
            .collect::<Result<_, _>>()
            .map_err(e)?;
        out.push(Table {
            name,
            columns,
            rows,
            total: total as u64,
        });
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::dump;

    #[test]
    fn dumps_tables_with_limit() {
        let mut con = rusqlite::Connection::open_in_memory().unwrap();
        con.execute_batch(
            "CREATE TABLE b(k TEXT, v INTEGER, x BLOB); CREATE TABLE \"a \"\"q\"(z REAL);
             INSERT INTO b VALUES('one', 1, x'0102'), ('two', NULL, NULL), ('three', 3, NULL);
             INSERT INTO \"a \"\"q\" VALUES(1.5);",
        )
        .unwrap();
        let img = con.serialize(rusqlite::MAIN_DB).unwrap();
        let t = dump(&img, None, Some(2)).unwrap();
        assert_eq!(
            t.iter().map(|t| t.name.as_str()).collect::<Vec<_>>(),
            ["a \"q", "b"]
        );
        assert_eq!(t[0].rows, [["1.5"]]);
        assert_eq!(t[1].columns, ["k", "v", "x"]);
        assert_eq!(t[1].total, 3);
        assert_eq!(t[1].rows, [["one", "1", "<blob 2 bytes>"], ["two", "", ""]]);
        let b = dump(&img, Some("b"), None).unwrap();
        assert_eq!((b.len(), b[0].rows.len()), (1, 3));
        assert!(dump(&img, Some("nope"), None).is_err());
    }

    #[test]
    fn opens_red_encrypted_db() {
        let pt = crate::preset::build_plaintext_db(7, &[("A".into(), "1".into())]).unwrap();
        let ct = crate::preset::encrypt_with(&pt, |p| [p as u8; crate::preset::RV]);
        assert!(!ct.starts_with(b"SQLite"));
        let t = dump(&ct, Some("parameters"), None).unwrap();
        assert_eq!(t[0].rows, [["A", "1"]]);
    }

    #[test]
    fn rejects_non_sqlite() {
        assert!(dump(&[0u8; 1024], None, Some(10)).is_err());
    }
}
