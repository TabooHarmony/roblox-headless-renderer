# scripts/groundtruth

`diff.py` is the pixel comparison used for Studio captures: it composites both
images over the same background and reports exact / within-2 / within-8 match
percentages, the max channel delta and the bounding box of differing pixels
(`tests/test_groundtruth_diff.py`). The committed RTL2PCParts pair in
`tests/groundtruth/` was scored with it (Pinevex's open example model).

Recording new ground truth from Studio is done with `scripts/studio/` (see
`tests/studio/README.md`), which compares numbers (rects, part transforms) rather
than pixels.
