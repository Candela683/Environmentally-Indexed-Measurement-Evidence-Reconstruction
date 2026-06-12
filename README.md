# Environmentally Indexed Measurement Evidence Reconstruction

Companion code for the manuscript:

```text
An evidence-to-model framework for reconstructing literature-derived contaminant measurements using a schema-guided large language model: a marine arsenic case study
```

Manuscript number: `ENVSOFT-D-26-01822`.

This repository provides a RIS-first workflow for reconstructing field-derived arsenic measurements in marine organisms. Article PDFs, full extracted article text, API credentials, NetCDF products, and large taxonomy resources are treated as local runtime resources rather than distributed source files.

## Repository Layout

```text
config/
  dashscope_models.yaml
  api_endpoints.example.yaml
  prompts/
    abstract_screening/
      screening_v1.yaml
    extraction/
      extraction_v1.yaml
      prompt_v1.txt
  review_stages.yaml

data/
  ris/
    example.ris
  articles/
    <source_id>/
      abstract_screening/
      source/
        <source_id>.pdf
        extracted_text/
        page_images/
        sections/
        figures/
        v1/
  cmems/
  geocoding/
  index/
  taxonomy/

notebooks/
  complete_workflow_example.ipynb

scripts/
src/
```

The main runnable example is:

```text
notebooks/complete_workflow_example.ipynb
```

## Setup

Use your own Python environment and install the dependencies:

```powershell
pip install -r requirements.txt
```

DashScope keys are read from the local environment or a local secret file.

```powershell
echo $env:DASHSCOPE_API_KEY
```

Model settings are configured in:

```text
config/dashscope_models.yaml
```

The OCR model is configured as:

```text
qwen-vl-ocr-2025-11-20
```

It is used for image-only papers, figure/table screenshots, abnormal PDF text extraction, and pages where concentration units are damaged by encoding.

## Input Data

The workflow starts from:

```text
data/ris/example.ris
```

RIS parsing uses `rispy`, so RIS exports from tools such as WoS, EndNote, Zotero, or publisher platforms can retain abstracts through standard fields such as `AB`.

PDFs are managed per article:

```text
data/articles/<source_id>/source/<source_id>.pdf
```

For example:

```text
data/articles/test_1/source/test_1.pdf
```

Large runtime resources are placed in the local data tree:

```text
data/cmems/
data/geocoding/shp/
data/taxonomy/
```

CMEMS NetCDF files belong under:

```text
data/cmems/
```

The environment matching code selects the nearest available year. If no matching year is available, it falls back to:

```text
Multi-year average.nc
```

## Workflow

### 1. RIS Indexing and Abstract Screening

```powershell
python scripts\run_ris_screening_demo.py
```

This reads `data/ris/example.ris`, writes:

```text
data/index/literature_index.csv
```

and screens publications using:

```text
config/prompts/abstract_screening/screening_v1.yaml
```

The abstract screening output is stored per article:

```text
data/articles/<source_id>/abstract_screening/v1/result.json
```

PDF download is not attempted before screening. If source download is needed after screening:

```powershell
python scripts\run_ris_screening_demo.py --download-source-files
```

Failed downloads are recorded as `source_file_status=manual` in `data/index/literature_index.csv`.

### 2. PDF Parsing

```powershell
python scripts\parse_article_sources.py
```

Each PDF is parsed into:

```text
source/extracted_text/
source/page_images/
source/sections/
source/figures/
```

Text layers are generated in priority order:

```text
full_text.txt
no_ref_text.txt
ocrl_text.txt
manual_text.txt
```

The later non-empty file has higher priority. `manual_text.txt` is created for human edits and is not overwritten once present.

OCR fallback is enabled by default. It is triggered when native PDF text is too short, visibly corrupted, or contains damaged concentration units. Unit symbols require particular care because many PDFs encode `µg`, `μg`, and related symbols through font-specific escape sequences. During extraction, a visually correct unit such as `µg/g` may appear in text as `Î¼g/g`, `汛g/g`, `�g/g`, or another corrupted token; in some cases the corruption appears immediately before or after `mg`, which can change the interpreted concentration unit. The parser therefore checks unit fragments around numeric concentrations with the same normalization logic used during harmonization. Pages with suspicious unit fragments are sent through OCR and the OCR text is stored separately before priority selection. To disable fallback:

```powershell
python scripts\parse_article_sources.py --no-ocr-fallback
```

### 3. Qwen Extraction and Concentration Agreement

Extraction prompt settings are in:

```text
config/prompts/extraction/extraction_v1.yaml
```

The run count is configured there:

```yaml
runs: 2
enable_thinking: true
```

Run extraction consensus:

```powershell
python scripts\run_extraction_consensus.py
```

For each article, the script selects the highest-priority text layer, calls Qwen for the configured number of runs, and keeps only records whose total arsenic concentration agrees across at least two runs.

Per-article outputs are stored under:

```text
data/articles/<source_id>/source/v1/
  prompt/
  raw_response/
  raw_json/
  parsed_csv/
  indexed_csv/
  final/
```

### 4. Review Workspace

After extraction, all non-article CSVs are staged under:

```text
data/review_workspace/
```

Each stage has:

```text
raw_csv/
manual_corrected_csv/
```

The next stage always reads from the previous stage's `manual_corrected_csv`.

Configured stages are:

```text
01_extraction_aggregation
02_measurement_harmonization
03_worms_taxonomy_matching
04_geographic_review
05_environment_matching
06_final_output
```

Run one stage:

```powershell
python scripts\run_review_workspace.py --stage extraction_aggregation
```

Run all stages:

```powershell
python scripts\run_review_workspace.py --stage all
```

Stage methods:

- `01_extraction_aggregation`: scans each article folder for `source/v1/final/concentration_consensus_records.csv`, appends the article folder name and the original DOI from `data/index/literature_index.csv`, and writes one combined extraction table.
- `02_measurement_harmonization`: applies numeric parsing, unit normalization, tissue labeling, and wet-weight conversion. Units such as `mg/kg`, `mg kg-1`, `ug/g`, `µg/g`, `μg/g`, `ug/kg`, and `ng/g` are normalized before conversion. Dry-weight values are converted with reported water content when available, otherwise with the configured moisture assumption used by `harmonize_records`.
- `03_worms_taxonomy_matching`: matches scientific names first by exact normalized spelling and then by genus-gated fuzzy matching. When a scientific name is missing or weak, common-name fields can be compared with local WoRMS or prepared taxonomy tables. Match type, score, matched name, and accepted taxonomy columns are retained for review.
- `04_geographic_review`: preserves reported coordinates, checks numeric validity, flags missing coordinates, zero-zero points, out-of-range values, and points outside the ocean polygon. Records requiring geographic review receive query fields for manual geocoding, plus empty columns for reviewed latitude and longitude.
- `05_environment_matching`: reads reviewed coordinates and selects local CMEMS NetCDF files. For each record, the nearest available year is preferred; when no suitable year-specific file is available, `Multi-year average.nc` is used. Physical and biogeochemical variables are sampled from the nearest grid cell, with the grid coordinate and match distance retained.
- `06_final_output`: copies the manually reviewed environment-matched records into the final reconstructed CSV stage, preserving the audit columns generated along the way.

## Notebook

The complete example notebook is:

```text
notebooks/complete_workflow_example.ipynb
```

It includes the full workflow and helper functions for plotting and lightweight modeling. Expensive steps are guarded by switches:

```python
RUN_REAL_QWEN = False
RUN_PDF_PARSE = False
RUN_REVIEW_STAGES = False
```

Set them to `True` only when you want to call models or regenerate outputs.

## Data and Copyright Notes

The distributed repository contains code, configuration templates, prompts, a small RIS example, and documentation. Local runs may create private or licensed runtime resources, including article PDFs, extracted article text, page images, OCR outputs, NetCDF files, taxonomy exports, and model responses. These runtime resources remain in the local data tree.

The included `test_1` article is a locally generated minimal example for workflow checking. Real literature files should be supplied by the user according to their own access rights.
