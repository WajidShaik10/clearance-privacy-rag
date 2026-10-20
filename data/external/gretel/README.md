# Gretel synthetic financial PII (sample)

500 rows of the `test` split of [gretelai/synthetic_pii_finance_multilingual](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) (license: Apache-2.0), downloaded with the Hugging Face datasets-server `rows` API (offsets 0-499, 100 rows per file). All data is synthetic.

Used only by `scripts/evaluate_unseen.py` to score the PII detector on documents it was not built from:
- rows 0-299 (English only) = **dev**: misses here may be looked at to improve the detector
- rows 300-499 (English only) = **test**: never looked at while improving; this is the honest score
