# Synthetic Marine Arsenic PDF Reconstruction Demo

This release bundle keeps one end-to-end test workflow:

1. generate a synthetic article PDF;
2. extract the abstract/table text from that PDF;
3. write a local SQLite database using a relative path;
4. run the complete reconstruction workflow;
5. inspect the generated outputs.

The synthetic PDF and tables are artificial. No copyrighted article text, private records, real API keys, cookies, or source PDFs are included.

## Main Notebook

Open:

```text
notebooks/synthetic_pdf_to_database_demo.ipynb
```

This is the only notebook demo kept in the bundle.

## Command Line Demo

Run:

```bash
python scripts/run_synthetic_pdf_demo.py
```

Use the `da` Conda environment explicitly on Windows:

```powershell
C:\Users\zpec\miniconda3\envs\da\python.exe -B scripts\run_synthetic_pdf_demo.py
```

If the current environment cannot write generated files into this project folder, pass a writable output root:

```powershell
C:\Users\zpec\miniconda3\envs\da\python.exe -B scripts\run_synthetic_pdf_demo.py C:\temp\arsenic_synthetic_demo
```

To run the same synthetic PDF through the real Qwen/DashScope extraction prompt, add `--qwen`.
The default prompt file is `templates/prompt_v1.txt`, so prompt-versioned artifacts are written under `pdf/v1/`.

```powershell
C:\Users\zpec\miniconda3\envs\da\python.exe -B scripts\run_synthetic_pdf_demo.py C:\temp\arsenic_synthetic_demo --qwen --prompt-template templates\prompt_v1.txt --qwen-runs 2
```

When running against this release folder itself from PowerShell, call the script from the parent directory and pass the release folder explicitly:

```powershell
cd D:\wuqiang\qiang\arsenic
C:\Users\zpec\miniconda3\envs\da\python.exe -B .\arsenic_reconstruction_release\scripts\run_synthetic_pdf_demo.py D:\wuqiang\qiang\arsenic\arsenic_reconstruction_release
```

## Import Local Assets

To copy local PDFs and database resources into the release folder, run:

```powershell
cd D:\wuqiang\qiang\arsenic
C:\Users\zpec\miniconda3\envs\da\python.exe -B .\arsenic_reconstruction_release\scripts\import_external_assets.py
```

The default import copies two `[Yes]` PDFs, WoRMS core files including `taxon.txt`, GBIF small name indexes, a small CMEMS subset, and a CMEMS source inventory. Large GBIF and CMEMS files are intentionally optional:

```powershell
C:\Users\zpec\miniconda3\envs\da\python.exe -B .\arsenic_reconstruction_release\scripts\import_external_assets.py --full-gbif
C:\Users\zpec\miniconda3\envs\da\python.exe -B .\arsenic_reconstruction_release\scripts\import_external_assets.py --full-cmems
```

Copied local data and generated outputs are ignored by `.gitignore` so they are not accidentally committed.

The script creates:

```text
synthetic_bundle/data_raw/literature/pdfs/[yes]+synthetic_marine_arsenic_article/
synthetic_bundle/data_raw/literature/pdfs/[yes]+synthetic_marine_arsenic_article/pdf/synthetic_arsenic_article.pdf
synthetic_bundle/data_raw/literature/pdfs/[yes]+synthetic_marine_arsenic_article/pdf/doi.txt
synthetic_bundle/data_raw/literature/pdfs/[yes]+synthetic_marine_arsenic_article/pdf/v1/
synthetic_bundle/data_raw/literature/pdfs/[yes]+synthetic_marine_arsenic_article/pdf/extracted_text/extracted_text.txt
synthetic_bundle/data_raw/literature/pdfs/[yes]+synthetic_marine_arsenic_article/pdf/extracted_tables/synthetic_measurements.csv
synthetic_bundle/data_raw/databases/sqlite/synthetic_arsenic_reconstruction.sqlite
synthetic_bundle/outputs/
synthetic_bundle/review_tables/
```

For each prompt version, the version folder keeps the audit trail:

- `prompt/`: the original prompt template and the filled prompt used for each run.
- `raw_response/`: raw model text responses.
- `raw_json/`: extracted JSON payloads before table conversion.
- `parsed_csv/`: parsed candidate rows from each run.
- `indexed_csv/`: parsed rows with `extraction_index`, `prompt_version`, and `prompt_run_number`.
- `final/`: the per-PDF final candidate table written into SQLite.

Project-level review tables are written outside the PDF folders:

- `review_tables/extracted_data/`: combined extraction CSVs from all PDF units for the prompt version.
- `review_tables/extracted_data/validated_for_manual_review/`: extraction CSVs exported after validation passes.
- `review_tables/geographic_mapping/`: coordinate-QC outputs; sample coordinates are not modified here.
- `review_tables/species_matching/`: taxonomy-matched records before environmental matching.
- `review_tables/environment_variable_matching/`: records after environmental variable matching.
- `review_tables/validation/`: final validation metrics and error-class summaries.
- `review_tables/complete_outputs/`: a complete copy of all workflow CSV outputs for review.

## PDF Generator

The code that creates the synthetic PDF is intentionally kept under `src/arsenic_workflow/devtools/`:

```text
src/arsenic_workflow/devtools/generate_synthetic_pdf.py
```

The PDF contains a synthetic title, abstract, methods paragraph, and a table of synthetic marine arsenic records. It is designed for software testing only.

## Relative Database Path

The SQLite database path is relative to this release folder:

```text
synthetic_bundle/data_raw/databases/sqlite/synthetic_arsenic_reconstruction.sqlite
```

The same relative path is documented in:

```text
config/synthetic_demo_config.yaml
```

## API Key Handling

The synthetic demo does not require network access. It checks whether DashScope is configured without printing the key value.

On Windows PowerShell, users can inspect their local key with:

```powershell
echo $env:DASHSCOPE_API_KEY
```

Endpoint examples are kept in:

```text
config/api_endpoints.example.yaml
```

Real API keys should be stored only as environment variables or local files under `config/secrets/`.

## DashScope Model Configuration

DashScope endpoints, model names, and local key lookup rules are configured in:

```text
config/dashscope_models.yaml
```

The current defaults are:

- extraction model: `qwen3.6-plus`
- extraction thinking: disabled
- screenshot OCR model: `qwen-vl-ocr-2025-11-20`
- question-answering model: `qwen3.6-plus`
- API base URL: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- API key source: `DASHSCOPE_API_KEY`, with optional local fallback `config/secrets/dashscope_api_key.txt`

Check the configuration without printing the key:

```powershell
C:\Users\zpec\miniconda3\envs\da\python.exe -B scripts\validate_dashscope_config.py
```

The reusable OCR and Qwen question-answering helpers are in:

```text
src/arsenic_workflow/dashscope_vision_qa.py
```

The PDF extraction workflow also reads `config/dashscope_models.yaml`; command-line `--model` is only an override for one run.

## NetCDF And Environmental Data

The demo does not copy large NetCDF files. It writes only the specific synthetic year-month environmental values needed by the PDF records into the SQLite table `environment_monthly`.

If a future test uses NetCDF, place only the small year-month slices needed by the synthetic records under:

```text
synthetic_bundle/data_raw/cmems/netcdf_subset/
```

## Workflow Outputs

The complete workflow writes:

- `00_input_discovery.csv`
- `01_duplicate_run_qc.csv`
- `02_candidate_record_qc.csv`
- `03_field_completeness.csv`
- `04_harmonized_records.csv`
- `05_coordinate_qc_no_point_modification.csv`
- `06_species_matched_records.csv`
- `07_environment_variable_matched_records.csv`
- `08_taxonomic_variance_proxy.csv`
- `09_environment_spearman_correlation.csv`
- `10_environment_models.csv`
- `11_taxon_environment_models.csv`
- `12_speciation_summary.csv`
- `13_validation_metrics.csv`
- `14_validation_error_classes.csv`

Environmental matching preserves the sample coordinates and only attaches nearest-grid values plus match distance.

## Folder Structure

```text
arsenic_reconstruction_release/
  README.md
  requirements.txt
  config/
    api_endpoints.example.yaml
    dashscope_models.yaml
    synthetic_demo_config.yaml
    secrets/
  templates/
    prompt_v1.txt
    qwen_extraction_prompt_template.txt
  notebooks/
    synthetic_pdf_to_database_demo.ipynb
  scripts/
    import_external_assets.py
    run_synthetic_pdf_demo.py
    validate_dashscope_config.py
  src/
    arsenic_workflow/
      dashscope_vision_qa.py
      llm_config.py
      devtools/
        generate_synthetic_pdf.py
  synthetic_bundle/
    data_raw/
      cmems/
        netcdf_subset/
      databases/
        sqlite/
      literature/
        pdfs/
          [yes]+synthetic_marine_arsenic_article/
            pdf/
              synthetic_arsenic_article.pdf
              doi.txt
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
    review_tables/
      extracted_data/
        validated_for_manual_review/
      geographic_mapping/
      species_matching/
      environment_variable_matching/
      validation/
      complete_outputs/
    outputs/
```
