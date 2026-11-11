//! The shipped golden_59c.json must give ZERO faults against a synthetic capture
//! built from the real 59C baseline values + the exact rail-name strings the shell
//! prints. This guards the golden rail-name keys against drift from parse_voltages.

use dsmc_core::baseline::*;
use dsmc_core::parse;
use std::collections::BTreeMap;

const GOLDEN: &str = include_str!("../golden_59c.json");

// exact live `test voltage all` output from the healthy 59C (BASELINE_59C_GOLDEN.md)
const VOLT_CAPTURE: &str = "\
Checking - IOB
  Vcc       1.0    = 1.006
  Vcc       1.5    = 1.494
  Vio_DV    1.8    = 1.805
  Vcc       2.5    = 2.501
  Vcc_DV    3.3    = 3.271
  Vcc       5.0    = 4.968
Checking - ISP
  Vcc_Isp   0.9    = 0.914
  Vcc_IspAVDD 0.9  = 0.906
  Vcc_Pll   1.5    = 1.526
  Vcc_AVDD  1.5    = 1.475
  Vcc_Isp   1.5    = 1.500
  Vref_Isp 0.75    = 0.746
  Vtt_Isp  0.75    = 0.739
  Vcc_Isp   1.8    = 1.799
  Vcc_Isp   2.5    = 2.489
Checking - Sensor
  Vdd_Tx    5.0    = 4.82065
  Vdd       1.8    = 1.79272
  Vdda_Pix  5.0    = 4.78305
  Vref_Adc  2.5    = 2.19508
  Vdda_Ramp        = 1.90063
  Vdda      1.8    = 1.78711
  Vdda      5.0    = 4.95224
  Vdd_Boost        = 5.78691
  VanaLogOut       = 0.76367
  Vdda_S    5.0    = 4.43214
  Vdd       5.0    = 4.96602
  GVDD      0.4    = 0.39746
  PARKAV    5.0    = 4.61699
Done
(97%/97%) dsh>";

const TEMP_CAPTURE: &str = "\
  IOB        = 51  Pass
  ISP        = 51  Pass
  Img Sensor = 39  Pass
  FPGA       = 61  Pass
  RSB        = 44  Pass
  Ambient    = 30  Pass
  LSB        = 57  Pass";

fn healthy_59c() -> Capture {
    let voltages: Vec<RailV> = parse::parse_voltages(VOLT_CAPTURE).into_iter()
        .map(|v| RailV { board: v.board, name: v.name, nominal: v.nominal, measured: v.measured }).collect();
    let temps: Vec<TempV> = parse::parse_temperatures(TEMP_CAPTURE).into_iter()
        .map(|t| TempV { sensor: t.sensor, celsius: t.celsius, pass: t.pass }).collect();

    let mut ddr = BTreeMap::new();
    ddr.insert("iob".into(), RamV { pass: true, saw_fail: false, done: true });
    ddr.insert("isp1".into(), RamV { pass: true, saw_fail: false, done: true });
    ddr.insert("isp0".into(), RamV { pass: false, saw_fail: true, done: true }); // the trap

    let i2c: Vec<I2cV> = [
        (1,0x38),(1,0x45),(1,0x48),(1,0x49),(1,0x4D),(1,0x52),(1,0x7C),
        (2,0x22),(2,0x47),(2,0x48),(2,0x4C),(2,0x65),(2,0x67),(2,0x6C),(2,0x70),
        (3,0x3B),(3,0x48),(3,0x57),(3,0x6E),
    ].iter().map(|&(b,a)| I2cV { bus: b, addr: a, label: "dev".into(), scan: "pass".into() }).collect();

    Capture {
        schema: 1,
        system_state: Some(StateVal { name: "READY_TO_RECORD".into(), code: 10 }),
        versions: Versions { isp: Some("D0".into()), iob: Some("B0".into()) },
        heartbeat: Some(0x1C),
        dragon_id: Some(0xE0),
        voltages, temps,
        x12: Some(LaneV { all_pass: true, lanes: 14, failing_lanes: vec![] }),
        x4_isp_rx: Some(LaneV { all_pass: true, lanes: 4, failing_lanes: vec![] }),
        x4_iob_rx: Some(LaneV { all_pass: true, lanes: 4, failing_lanes: vec![] }),
        ucd: vec![
            UcdV { board: "iob".into(), bus: 1, addr: 0x7C, part: "UCD9090".into(), status_vout_all_ok: true, flags: vec![] },
            UcdV { board: "isp".into(), bus: 2, addr: 0x70, part: "UCD9090".into(), status_vout_all_ok: true, flags: vec![] },
            UcdV { board: "sensor".into(), bus: 2, addr: 0x65, part: "UCD90160".into(), status_vout_all_ok: true, flags: vec![] },
        ],
        i2c, ddr,
        ..Default::default()
    }
}

#[test]
fn shipped_golden_passes_healthy_59c() {
    let golden = Golden::from_json(GOLDEN).expect("golden_59c.json must parse");
    let cap = healthy_59c();
    let rows = assert_capture(&golden, &cap);
    let fails: Vec<_> = rows.iter().filter(|r| r.verdict == Verdict::Fail).collect();
    assert!(fails.is_empty(), "golden should PASS the healthy 59C, but got FAILs: {:#?}", fails);
    assert_eq!(fault_count(&rows), 0);
    // the ISP0 DDR trap must be EXPECTED-PASS
    assert!(rows.iter().any(|r| r.signal == "test ram isp0" && r.verdict == Verdict::ExpectedPass));
    // every voltage rail must have matched a golden window (no INFO "(no window)" rows)
    let no_window: Vec<_> = rows.iter().filter(|r| r.signal.starts_with("V ") && r.golden == "(no window)").collect();
    assert!(no_window.is_empty(), "these rails have no golden window (name mismatch): {:#?}",
        no_window.iter().map(|r| &r.signal).collect::<Vec<_>>());
}
