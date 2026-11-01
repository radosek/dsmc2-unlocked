# Research Notes — Difficulties and Insights

This document tells the story behind the findings. It gives the problems, the
surprises, and the ideas that unblocked the work. It stays at the level of what
happened and why it mattered. It does not give methods, addresses, or access
steps.
## Problem 1 — getting data off the camera was slow

The low-level read path is very slow. It moves only a few kilobytes per second.
The camera filesystem is about 490 files and 160 MB. At that speed a full copy
takes about half a day. It also keeps the bench busy the whole time.

This slowed every step. Each new idea needed a new file. Each new file meant
another long wait.

## Insight 1 — the compressor is really a read tool

The firmware has a built-in compressor. The camera uses it for its own data. The
important point is different: the compressor is a **read-and-copy tool in
disguise**. You give it a source location. It reads what is there. It writes the
result to a place you can collect.

The value was not the compression. We did not want smaller files. Much of the data
did not compress at all. It came out the same size or larger. We still used the
compressor, because the compressor was the part that could **reach** the data and
give it back.

So the real capability was arbitrary read-and-copy. Compression was only a side
effect. After this change the full copy took minutes, not half a day. The whole
project then moved faster.

**Lesson.** The use of a device feature is often not its label. A "compress this
file" tool is also a "read this location and give it to me" tool. Look at a
feature for the basic action it gives you, not for the name on the button.

## Problem 2 — a "second encryption layer" that did not exist

For a while we believed the firmware had a **second, unbroken encryption layer**.
A multi-model package seemed to hold sealed, random data under the part we could
open. We looked for an inner key for days.

There was no inner layer. The "sealed" data was already plain. Our own tool had run
its decryption step **over data that was not encrypted**, and that turned readable
bytes back into noise. The noise then looked like a cipher we had not broken. We
were the ones who encrypted it.

Once we stopped double-processing the data, a multi-model package opened fully. The
firmware we unpacked offline is **byte-for-byte the same** as the image on the
camera. See [firmware.md](firmware.md) for the real structure.

**Lesson.** Randomness cuts both ways. Random output can mean "still encrypted," but
it can also mean "you just encrypted plain data by mistake." Before you hunt a
missing key, check that your own pipeline did not create the very ciphertext you are
chasing.

## Insight 2 — keep the wrong turns in the record

Several early notes were later marked wrong. The record keeps both the wrong note
and the correction. Examples:

- A claimed secret key that "locked" the firmware did not exist in the form the
  first pass described.
- A boot assumption ("we need one special low-level block to continue") was wrong.
  The needed part came from another source and did not check what the theory
  assumed.
- In the media work, an early read split one byte wrongly. That byte is part of
  the hash, not a separate marker.

This is why the public docs are careful where the evidence stopped. See the
cautions in [whats-possible.md](whats-possible.md) and [models.md](models.md).

## Problem 3 — some memory is not safe to read

The processor uses one flat memory space with no protection. Reading the wrong
area can crash the camera. Boot ROM, some peripheral and crypto registers, and a
few coprocessor test paths all cause crashes. Only the main application memory is
safe to read.

Much early effort went into a safe-area map. Respecting that map let the later work
run without constant reboots.

**Lesson.** On a flat system with no protection, "read everything" is a fast way to
lock up the device. A tested safe-area map is worth the time.

## Insight 3 — the media lock was weaker than it looked

The MINI-MAG check looked like real cryptography. It looked like a signed block
that the camera verifies. It is not. It is a plain, standard hash over a few
identity fields, plus an exact text match. There is no public-key signature, no
server, and no secret unique to each drive. The full write-up is in the
[media](../media/) folder.

**Lesson.** Name the method before you assume it is strong. The word "signature" in
a vendor's code can mean a strong RSA signature or a simple hash over a value.
Those are very different. Only the disassembly tells you which one you face.

## Why the platform was workable

A few facts made the work possible for one person:

- **A flat real-time OS with no memory protection.** Once you can run or watch
  code, the whole memory is visible and consistent. The same fact is why careless
  reads crash the camera.
- **Mostly standard, known parts.** A common database, a common compression
  library, a known crypto library, a common flash filesystem, and plain XML. If you
  recognise a standard part, you get its format for free.
- **Plain-text per-model manifests.** Model differences are readable because the
  manifests are plain XML. This is what let us separate "identity is config" from
  "capability is hardware" in an honest way.

None of these facts are secret. They only describe how the camera is built.
