#!/usr/bin/env bun
/** Decrypt RED DSMC2 camera binary log files.
 *
 * Usage: bun run decode_red_log.ts <input_file> [output_file]
 */

const RECORD_SIZE = 512;

function mostCommon(arr: number[]): number {
  const freq = new Map<number, number>();
  for (const v of arr) freq.set(v, (freq.get(v) ?? 0) + 1);
  let best = arr[0], bestN = 0;
  for (const [k, n] of freq) if (n > bestN) { best = k; bestN = n; }
  return best;
}

async function decode(infile: string, outfile?: string): Promise<string> {
  const bytes = new Uint8Array(await Bun.file(infile).arrayBuffer());
  const numRecords = Math.floor(bytes.length / RECORD_SIZE);

  const kEven = new Uint8Array(RECORD_SIZE);
  for (let pos = 0; pos < RECORD_SIZE; pos++) {
    const vals: number[] = [];
    for (let r = 0; r < numRecords; r += 2) vals.push(bytes[r * RECORD_SIZE + pos]);
    kEven[pos] = mostCommon(vals) ^ 0x20;
  }

  const kOdd = new Uint8Array(RECORD_SIZE);
  for (let pos = 0; pos < RECORD_SIZE; pos++) {
    const vals: number[] = [];
    for (let r = 1; r < numRecords; r += 2) vals.push(bytes[r * RECORD_SIZE + pos]);
    kOdd[pos] = mostCommon(vals) ^ 0x20;
  }

  const lines: string[] = [];
  for (let r = 0; r < numRecords; r++) {
    const key = r % 2 === 0 ? kEven : kOdd;
    let line = '';
    for (let i = 0; i < RECORD_SIZE; i++) {
      const b = bytes[r * RECORD_SIZE + i] ^ key[i];
      line += b >= 32 && b < 127 ? String.fromCharCode(b) : b === 0 ? '' : String.fromCharCode(b);
    }
    lines.push(line);
  }

  const outPath = outfile ?? infile + '.decoded';
  await Bun.write(outPath, lines.join('\n'));
  return outPath;
}

const infile = Bun.argv[2];
if (!infile) {
  console.log(`Usage: bun run ${Bun.argv[1].split('/').pop()} <input_file> [output_file]`);
  process.exit(1);
}
const outfile = Bun.argv[3];
console.log(`Decoded: ${await decode(infile, outfile)}`);
