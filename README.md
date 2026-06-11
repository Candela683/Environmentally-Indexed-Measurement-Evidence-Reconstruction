# Environmentally Indexed Measurement Evidence Reconstruction

This repository contains the runnable reconstruction workflow for marine arsenic measurement evidence.

The workflow is organized around PDF units. Each selected article is stored as a folder named with the `[yes]+...` prefix. In this project, `[yes]` means the PDF has been selected and confirmed for the reconstruction workflow.

Large local resources such as PDFs, SQLite databases, NetCDF slices, taxonomy files, and generated run outputs are kept in the local working folder and ignored by Git. The repository keeps the code, configuration, notebook demo, prompt templates, and folder structure needed to rebuild or rerun the workflow.

## Main Entry Points

Notebook demo:

```text
notebooks/synthetic_pdf_to_database_demo.ipynb
```

Command-line synthetic PDF demo:

```powershell
python scripts\run_synthetic_pdf_demo.py
```

When running from the parent project folder, pass this repository folder explicitly:

```powershell
python .\arsenic_reconstruction_release\scripts\run_synthetic_pdf_demo.py D:\wuqiang\qiang\arsenic\arsenic_reconstruction_release
```

Use the Python or Conda environment that contains the packages listed in `requirements.txt`.

## Qwen / DashScope Configuration

DashScope model and endpoint settings are configured here:

```text
config/dashscope_models.yaml
```

Current defaults:

- extraction model: `qwen3.6-plus`
- screenshot OCR model: `qwen-vl-ocr-2025-11-20`
- question-answering model: `qwen3.6-plus`
- API base URL: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- API key source: environment variable `DASHSCOPE_API_KEY`

Check configuration without printing the key:

```powershell
python scripts\validate_dashscope_config.py
```

Run the synthetic PDF through the real Qwen extraction prompt:

```powershell
python scripts\run_synthetic_pdf_demo.py . --qwen --prompt-template templates\prompt_v1.txt --qwen-runs 2
```

Prompt-versioned extraction artifacts are written under the PDF folder, for example:

```text
synthetic_bundle/data_raw/literature/pdfs/[yes]+synthetic_marine_arsenic_article/pdf/v1/
```

Each prompt version keeps:

- `prompt/`: prompt template and filled prompts for each run.
- `raw_response/`: raw model responses.
- `raw_json/`: extracted JSON payloads.
- `parsed_csv/`: parsed records from each run.
- `indexed_csv/`: parsed records with prompt/run indexes.
- `final/`: final per-PDF candidate table used by the downstream workflow.

## Local Data Import

Copy selected local PDFs and reference resources into the repository working folder:

```powershell
python scripts\import_external_assets.py
```

The import script copies selected `[yes]` PDFs, WoRMS files, GBIF name indexes, and a small CMEMS subset into `synthetic_bundle/data_raw/`.

Optional larger imports:

```powershell
python scripts\import_external_assets.py --full-gbif
python scripts\import_external_assets.py --full-cmems
```

These copied assets remain local and are ignored by Git.

## Review Tables

Per-PDF extraction files stay inside each PDF unit. Cross-PDF review tables are written outside the PDF folders:

```text
synthetic_bundle/review_tables/
```

Main review stages:

- `extracted_data/`: combined extraction CSVs by prompt version.
- `extracted_data/validated_for_manual_review/`: extraction records after validation checks.
- `geographic_mapping/`: coordinate QC outputs; coordinates are not rewritten.
- `species_matching/`: taxonomy-matched records.
- `environment_variable_matching/`: records after environmental variable matching.
- `validation/`: validation metrics and error-class summaries.
- `complete_outputs/`: complete copy of workflow CSV outputs.

## Workflow Outputs

The full workflow writes:

```text
00_input_discovery.csv
01_duplicate_run_qc.csv
02_candidate_record_qc.csv
03_field_completeness.csv
04_harmonized_records.csv
05_coordinate_qc_no_point_modification.csv
06_species_matched_records.csv
07_environment_variable_matched_records.csv
08_taxonomic_variance_proxy.csv
09_environment_spearman_correlation.csv
10_environment_models.csv
11_taxon_environment_models.csv
12_speciation_summary.csv
13_validation_metrics.csv
14_validation_error_classes.csv
```

Environmental matching attaches nearest-grid values and match distance while preserving the sample coordinates.

## Synthetic PDF Generator

The synthetic PDF generator is kept in:

```text
src/arsenic_workflow/devtools/generate_synthetic_pdf.py
```

It creates a small article-style PDF with an abstract, methods text, and table data for workflow testing.

## Folder Structure

```text
arsenic_reconstruction_release/
  config/
    dashscope_models.yaml
    synthetic_demo_config.yaml
    secrets/
  notebooks/
    synthetic_pdf_to_database_demo.ipynb
  scripts/
    import_external_assets.py
    run_synthetic_pdf_demo.py
    validate_dashscope_config.py
  src/
    arsenic_workflow/
      devtools/
        generate_synthetic_pdf.py
  synthetic_bundle/
    data_raw/
      cmems/
      databases/
      literature/
        pdfs/
          [yes]+synthetic_marine_arsenic_article/
            pdf/
              source_metadata/
              extracted_text/
              extracted_tables/
              v1/
                prompt/
                raw_response/
                raw_json/
                parsed_csv/
                indexed_csv/
                final/
      taxonomy/
    review_tables/
      extracted_data/
      geographic_mapping/
      species_matching/
      environment_variable_matching/
      validation/
      complete_outputs/
    outputs/
  templates/
    prompt_v1.txt
```
