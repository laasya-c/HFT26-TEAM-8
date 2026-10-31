# WILDSCOPE — Inference Component Licensing

> **Summary: The current stack is NOT cleared for commercial distribution or
> public deployment.  Legal review is required before any release.**

> [!IMPORTANT]
> This document is a good-faith technical summary produced for the WILDSCOPE
> hackathon prototype.  It is **not legal advice**.  Licence texts, conditions,
> and interpretations can be complex and fact-specific.  For any commercial,
> public, or production deployment, engage a qualified lawyer before relying on
> the conclusions or characterisations in this document.

---

## 1. SpeciesNet Package (`speciesnet==5.0.5`)

| Item | Detail |
|:--|:--|
| Publisher | Google LLC |
| License | **Apache License 2.0** |
| Source | https://github.com/google/speciesnet |
| Model weights | Distributed via KaggleHub / HuggingFace Hub |
| Commercial use | Permitted under Apache-2.0, subject to conditions |

**Key Apache-2.0 conditions:**
- Retain copyright and licence notices in all distributions.
- State changes made to the original code.
- Do not use Google trademarks without permission.

**Note:** The Apache-2.0 licence applies to the SpeciesNet Python package and
its stated model weights as declared on the distribution pages inspected.
Whether every bundled component, transitive dependency, or future version of
SpeciesNet carries the same licence has not been independently verified.
For any public or commercial release, retain all copyright notices and
attribution and verify the licences of all components at the time of release.

---

## 2. SpeciesNet Model Weights

| Item | Detail |
|:--|:--|
| Model | `google/speciesnet/pyTorch/v4.0.3a/1` |
| Hosted on | Kaggle Model Hub |
| License | Apache License 2.0 (as stated on the Kaggle model page at time of inspection) |
| Download | Via `kagglehub` — requires Kaggle account |

**Note:** The Apache-2.0 licence is the licence declared on the Kaggle model
page.  The provenance and licensing of all data used to train the model have
not been independently verified.  The same Apache-2.0 conditions as the
package apply to redistribution of the weights.

---

## 3. MegaDetector (Bundled inside SpeciesNet)

| Item | Detail |
|:--|:--|
| Origin | Microsoft AI for Earth / agentmorris/MegaDetector |
| SpeciesNet comment | `# Code adapted from: https://github.com/agentmorris/MegaDetector` |
| MegaDetector license | **MIT License** |
| Reference | https://github.com/agentmorris/MegaDetector/blob/main/LICENSE |

The MegaDetector V5 architecture and its adapted inference code inside
`speciesnet/detector.py` carry an MIT licence attribution comment.  MIT is a
permissive licence compatible with Apache-2.0.

**Note:** Only the attribution comment in the source was inspected.  The full
extent of adapted code and whether all adapted portions are covered by the MIT
licence has not been independently audited.

---

## 4. YOLOv5 (`yolov5==7.0.11`) — **COPYLEFT — LEGAL REVIEW REQUIRED**

| Item | Detail |
|:--|:--|
| PyPI package | `yolov5==7.0.11` (distributed via `fcakyon/yolov5-pip`) |
| Pinned by | `speciesnet==5.0.5` as a transitive dependency |
| License — installed dist-info | **GPL-3.0** (`yolov5-7.0.11.dist-info/METADATA`: `License: GPL`; `dist-info/LICENSE`: GPL v3 text) |
| License — upstream GitHub | `ultralytics/yolov5` repository carries **AGPL-3.0** at the v7.0.x tag |
| Evidence inspected | `.venv/Lib/site-packages/yolov5-7.0.11.dist-info/METADATA` and `LICENSE` on 2026-10-31 |

### What the evidence shows

The `yolov5==7.0.11` package installed from PyPI (via the `fcakyon/yolov5-pip`
wrapper) declares **GPL-3.0** in both its `METADATA` field and its bundled
`LICENSE` file.  This is the licence governing the installed copy.

The upstream Ultralytics repository (`ultralytics/yolov5`) migrated to
AGPL-3.0 after version 5.x.  The PyPI wrapper package continued to declare
GPL-3.0.  **Whether the installed wheel's GPL-3.0 declaration correctly
reflects the licensing of all bundled model weights, utilities, and adapted
code has not been independently audited.**  Legal review is required before
any distribution or deployment.

### GPL-3.0 vs AGPL-3.0 — key distinction

| Scenario | GPL-3.0 obligation | AGPL-3.0 obligation |
|:--|:--|:--|
| Internal / hackathon use (no distribution) | None triggered | None triggered |
| Distributing compiled software | Must release all derived source under GPL-3.0 | Must release all derived source under AGPL-3.0 |
| Running as a **network service** | **No additional obligation** | Source must be offered to all users of the service |

If the installed copy's GPL-3.0 declaration is accurate, a future WILDSCOPE
web API would not trigger the network-service source-release obligation that
AGPL-3.0 carries.  However, distributing any compiled application containing
this code would still require releasing all derived source under GPL-3.0 terms
— or obtaining a separate commercial licence.

> [!IMPORTANT]
> These characterisations are based on a surface reading of the installed
> metadata and are not legal conclusions.  Do not rely on them without
> independent legal review, particularly because the upstream repository's
> AGPL-3.0 and the PyPI wrapper's GPL-3.0 declaration conflict.

### Current status in WILDSCOPE

- WILDSCOPE currently uses this stack **exclusively for a hackathon prototype**.
- No software is being distributed.  No network service is being offered.
- Under these conditions the copyleft obligations of either GPL-3.0 or
  AGPL-3.0 are not triggered by distribution or network use.
- This does **not** constitute clearance for any future release or deployment.

### What must be resolved before any release

1. **Obtain a qualified legal opinion** on which licence governs the installed
   copy, taking into account the conflict between the PyPI metadata (GPL-3.0)
   and the upstream repository (AGPL-3.0).

2. **Inspect all bundled components** inside the installed `yolov5` package
   (model weights, adapted utilities) to confirm they are all covered by the
   declared GPL-3.0.

3. **Obtain a commercial licence from Ultralytics** if closed-source or
   proprietary deployment is needed.  Contact: https://ultralytics.com/license

4. **Or replace the detector** with a non-copyleft alternative (e.g.,
   MegaDetector V6, which uses RT-DETR / transformers).  The `BaseDetector`
   interface in `src/inference/base_detector.py` was designed explicitly to
   make this swap possible without changing any consumer code.

> **Do NOT describe the current WILDSCOPE inference stack as commercially
> cleared or open-source safe for distribution until legal review is complete.**

---

## 5. Caltech Camera Traps Dataset (CCT)

| Item | Detail |
|:--|:--|
| Publisher | Justin Kay, Timnit Gebru et al. / LILA Science |
| License | **CDLA-Permissive-1.0** (as declared on the LILA Science dataset page) |
| Reference | https://lila.science/datasets/caltech-camera-traps |

CDLA-Permissive-1.0 is described as a permissive data licence.  Key stated
conditions include:

- **Attribution:** Retain the data source credit when sharing or publishing
  results derived from the dataset.
- **No copyleft on derived works:** The licence does not require derivative
  datasets or models trained on the data to be released under the same terms.

**Note:** The CCT dataset licence as declared on the LILA Science page is
CDLA-Permissive-1.0.  Whether all images in the dataset were collected and
licensed consistently — including third-party contributions or images sourced
from camera trap operators — has not been independently verified.  For any
public release or commercial product that includes results derived from CCT
data, verify the dataset's current licence terms directly on the LILA Science
page and retain appropriate attribution.  This document does not provide
clearance for any specific commercial use.

---

## 6. WILDSCOPE Inference Code (this repo)

All code in `src/inference/` and `tests/inference/` written by Team ByteStrom
for this hackathon is **original work**.  No licence has been chosen yet.  Until
a licence is selected, all rights are reserved by the authors.

---

## 7. Summary Table

| Component | Declared Licence | Notes |
|:--|:--|:--|
| `speciesnet` Python package | Apache-2.0 | As declared; full component audit not performed |
| SpeciesNet model weights | Apache-2.0 | As declared on Kaggle model page |
| MegaDetector (adapted code) | MIT | Attribution comment inspected; full audit not performed |
| `yolov5==7.0.11` (PyPI dist-info) | **GPL-3.0** (declared) | Conflicts with upstream AGPL-3.0; **legal review required** |
| CCT dataset | CDLA-Permissive-1.0 | Attribution required; verify terms for specific commercial use |
| WILDSCOPE inference code | All rights reserved (no licence chosen) | — |

---

## 8. Recommended Next Actions

1. **Obtain legal review** of the YOLOv5 GPL-3.0 / AGPL-3.0 conflict before
   any distribution or deployment.
2. **Decide** deployment model: internal prototype only, or public/commercial
   service?
3. If public/commercial: **engage Ultralytics** for a commercial YOLOv5 licence
   **or** **swap the detector** to a non-copyleft implementation via
   `BaseDetector`.
4. **Choose a licence** for the WILDSCOPE codebase itself before any public
   release.
5. **Verify CCT dataset terms** directly on lila.science before publishing any
   derived results commercially.
