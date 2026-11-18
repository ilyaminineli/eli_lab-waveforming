# WAVEFORMING HTML layout migration report

Native top-left canvas geometry is preserved in 1920×1440 pixel coordinates.

## Findings

- layout.html: 23 image layers, 6 groups, 28,287,989 bytes.
- layout_simple.html: 18 image layers, 6 groups, 25,951,452 bytes.
- Deduplicated embedded PNGs: 22 unique assets, 21,187,612 bytes.
- Identical positioned layer instances: 18.
- Full-only layers: image_10, image_20, image_21, image_22, image_23.
- Simple-only layers: none.

## Preserve

Keep page size, image assets, source rectangles, accumulated group offsets, DOM z-order, group paths, opacity, blend modes, rotation, transform origin, visibility, filters, isolation and nested image styles.
The 1322×1058 artwork frame in the HTML files is [217, 188, 1539, 1246]. The legacy printable-area rectangle in layout_profiles.json is [299, 191, 1621, 1249]. These values have different provenance and must not be conflated.
resources/screens/pre_designed/Scr1.png through Scr7.png are separate pre-rendered screens, not substitutes for these HTML layers.

## Layer inventories

### layout.html

| Z | Layer | Group path | Absolute rect [x,y,w,h] | Opacity | Blend | Asset |
|---:|---|---|---|---:|---|---|
| 0 | image_1 | page | 0, 0, 1920, 1440 | 1 | normal | parts/layer_db430a5c54b85649.png |
| 1 | image_2 | group_24/group_25 | 0, 0, 1920, 1440 | 1 | screen | parts/layer_219faf3075dd7267.png |
| 2 | image_3 | group_24/group_25 | 0, 0, 1920, 1440 | 1 | screen | parts/layer_31c95f8f42c66f9d.png |
| 3 | image_4 | group_24/group_25/group_26 | 0, 0, 1920, 1440 | 0.388235 | color-burn | parts/layer_f997851a4bdf975c.png |
| 4 | image_5 | group_24/group_25/group_26 | 0, 0, 1920, 1440 | 0.458824 | exclusion | parts/layer_2ffb5b41c0c12dc7.png |
| 5 | image_6 | group_24/group_25/group_26 | 0, 0, 1920, 1440 | 0.501961 | exclusion | parts/layer_612ba5a05a9da60d.png |
| 6 | image_7 | group_24/group_25/group_26 | 0, 0, 1920, 1440 | 0.478431 | hard-light | parts/layer_bcc811853865d37a.png |
| 7 | image_8 | group_24/group_25/group_27 | -19, -272, 1958, 1958 | 1 | multiply | parts/layer_bdc814bdc07b207e.png |
| 8 | image_9 | group_24/group_25/group_27 | 0, 0, 1920, 1440 | 0.8 | screen | parts/layer_5e232979b68c5453.png |
| 9 | image_10 | group_24/group_28 | 473, 386, 972, 668 | 1 | luminosity | parts/layer_8b3047d447276821.png |
| 10 | image_11 | group_24/group_28 | 1235, 1299, 529, 69 | 1 | normal | parts/layer_a41b520f9c1f0aae.png |
| 11 | image_12 | group_24/group_28 | 111, 1299, 529, 69 | 1 | normal | parts/layer_7c8f7b727c7a4e83.png |
| 12 | image_13 | group_24/group_28 | 1573, 453, 36, 443 | 1 | normal | parts/layer_4fd614903df45f2c.png |
| 13 | image_14 | group_24/group_28 | 309, 453, 36, 443 | 1 | normal | parts/layer_4fd614903df45f2c.png |
| 14 | image_15 | group_24/group_28 | 18, 453, 36, 534 | 1 | normal | parts/layer_70fa7d15014572c8.png |
| 15 | image_16 | group_24/group_28 | 0, 0, 222, 223 | 1 | normal | parts/layer_8cfb3f1134870293.png |
| 16 | image_17 | group_24/group_28 | 1866, 453, 36, 534 | 1 | normal | parts/layer_e3088a393ce4cb22.png |
| 17 | image_18 | group_24/group_28 | 1698, 0, 222, 223 | 1 | normal | parts/layer_1f1b2db3e3ef5264.png |
| 18 | image_19 | group_24/group_29 | 217, 188, 1322, 1058 | 1 | screen | parts/layer_d0286bda6690fd7b.png |
| 19 | image_20 | group_24 | 1167, 272, 521, 896 | 1 | lighten | parts/layer_6bc824eedf4acb2f.png |
| 20 | image_21 | group_24 | 376, 360, 499, 402 | 1 | difference | parts/layer_83fd34cf480a86a2.png |
| 21 | image_22 | group_24 | 906, 62, 402, 499 | 1 | difference | parts/layer_faa03dae2ff30c1a.png |
| 22 | image_23 | group_24 | 919, 636, 466, 253 | 1 | exclusion | parts/layer_1d74ef8c44c13949.png |

### layout_simple.html

| Z | Layer | Group path | Absolute rect [x,y,w,h] | Opacity | Blend | Asset |
|---:|---|---|---|---:|---|---|
| 0 | image_1 | page | 0, 0, 1920, 1440 | 1 | normal | parts/layer_db430a5c54b85649.png |
| 1 | image_2 | group_19/group_20 | 0, 0, 1920, 1440 | 1 | screen | parts/layer_219faf3075dd7267.png |
| 2 | image_3 | group_19/group_20 | 0, 0, 1920, 1440 | 1 | screen | parts/layer_31c95f8f42c66f9d.png |
| 3 | image_4 | group_19/group_20/group_21 | 0, 0, 1920, 1440 | 0.388235 | color-burn | parts/layer_f997851a4bdf975c.png |
| 4 | image_5 | group_19/group_20/group_21 | 0, 0, 1920, 1440 | 0.458824 | exclusion | parts/layer_2ffb5b41c0c12dc7.png |
| 5 | image_6 | group_19/group_20/group_21 | 0, 0, 1920, 1440 | 0.501961 | exclusion | parts/layer_612ba5a05a9da60d.png |
| 6 | image_7 | group_19/group_20/group_21 | 0, 0, 1920, 1440 | 0.478431 | hard-light | parts/layer_bcc811853865d37a.png |
| 7 | image_8 | group_19/group_20/group_22 | -19, -272, 1958, 1958 | 1 | multiply | parts/layer_bdc814bdc07b207e.png |
| 8 | image_9 | group_19/group_20/group_22 | 0, 0, 1920, 1440 | 0.8 | screen | parts/layer_5e232979b68c5453.png |
| 9 | image_10 | group_19/group_23 | 1235, 1299, 529, 69 | 1 | normal | parts/layer_a41b520f9c1f0aae.png |
| 10 | image_11 | group_19/group_23 | 111, 1299, 529, 69 | 1 | normal | parts/layer_7c8f7b727c7a4e83.png |
| 11 | image_12 | group_19/group_23 | 1573, 453, 36, 443 | 1 | normal | parts/layer_4fd614903df45f2c.png |
| 12 | image_13 | group_19/group_23 | 309, 453, 36, 443 | 1 | normal | parts/layer_4fd614903df45f2c.png |
| 13 | image_14 | group_19/group_23 | 18, 453, 36, 534 | 1 | normal | parts/layer_70fa7d15014572c8.png |
| 14 | image_15 | group_19/group_23 | 0, 0, 222, 223 | 1 | normal | parts/layer_8cfb3f1134870293.png |
| 15 | image_16 | group_19/group_23 | 1866, 453, 36, 534 | 1 | normal | parts/layer_e3088a393ce4cb22.png |
| 16 | image_17 | group_19/group_23 | 1698, 0, 222, 223 | 1 | normal | parts/layer_1f1b2db3e3ef5264.png |
| 17 | image_18 | group_19/group_24 | 217, 188, 1322, 1058 | 1 | screen | parts/layer_d0286bda6690fd7b.png |

## Deletion guidance

The HTML exports are static wrappers around embedded images and inline styles. They are no longer required at runtime once the extracted parts and manifest are committed and a visual reconstruction is checked against both source variants. Keep the HTML files until that verification is complete.
