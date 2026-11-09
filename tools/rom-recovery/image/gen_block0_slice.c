/* gen_block0_slice — emit a C header with block-0 pages [FIRST,LAST) as uint16 LE arrays
 * for the restore image. Reads the block-0 dump from env:
 *   RED_GOLDEN_MAIN  = main-only dump  (64 * 2048 bytes)
 *   RED_GOLDEN_SPARE = spare-only dump (64 * 64 bytes)
 * Usage: gen_block0_slice FIRST LAST OUT.h
 * Host tool — build with the host cc, not the ARM cross-compiler. */
#include <stdio.h>
#include <stdlib.h>

#define PAGES 64
#define MAIN  2048
#define SPARE 64

static unsigned char *slurp(const char *env, long want)
{
	const char *path = getenv(env);
	if (!path) { fprintf(stderr, "set %s to your block0 dump\n", env); exit(1); }
	FILE *f = fopen(path, "rb");
	if (!f) { fprintf(stderr, "cannot open %s (%s)\n", env, path); exit(1); }
	unsigned char *buf = malloc(want);
	long got = (long)fread(buf, 1, want, f);
	fclose(f);
	if (got < want) { fprintf(stderr, "%s: short read %ld < %ld\n", path, got, want); exit(1); }
	return buf;
}

static void emit(FILE *o, const char *name, const unsigned char *b, int first, int last, int bytes_per_page)
{
	int total = (last - first) * bytes_per_page / 2;   /* uint16 words */
	fprintf(o, "static const unsigned short %s[%d] = {\n", name, total);
	int n = 0;
	for (int p = first; p < last; p++) {
		const unsigned char *pg = b + p * bytes_per_page;
		for (int i = 0; i < bytes_per_page; i += 2) {
			fprintf(o, "0x%04x,", pg[i] | (pg[i + 1] << 8));
			if (++n % 12 == 0) fputc('\n', o);
		}
	}
	fprintf(o, "\n};\n");
}

int main(int argc, char **argv)
{
	if (argc != 4) { fprintf(stderr, "usage: %s FIRST LAST OUT.h\n", argv[0]); return 1; }
	int first = atoi(argv[1]), last = atoi(argv[2]);
	if (first < 0 || last > PAGES || first >= last) { fprintf(stderr, "bad page range\n"); return 1; }

	unsigned char *main_ = slurp("RED_GOLDEN_MAIN", (long)PAGES * MAIN);
	unsigned char *spare = slurp("RED_GOLDEN_SPARE", (long)PAGES * SPARE);

	FILE *o = fopen(argv[3], "w");
	if (!o) { fprintf(stderr, "cannot write %s\n", argv[3]); return 1; }
	fprintf(o, "/* block0 pages %d..%d */\n", first, last - 1);
	fprintf(o, "#define RED_B0_FIRST %d\n#define RED_B0_LAST %d\n", first, last);
	emit(o, "red_b0_main", main_, first, last, MAIN);
	emit(o, "red_b0_spare", spare, first, last, SPARE);
	fclose(o);
	printf("%s: pages %d..%d (%d B main, %d B spare)\n",
	       argv[3], first, last - 1, (last - first) * MAIN, (last - first) * SPARE);
	return 0;
}
