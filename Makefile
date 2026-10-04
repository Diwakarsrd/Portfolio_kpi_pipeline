.PHONY: setup data mappings test raw final app evaluate readme all
setup:      ; pip install -r requirements.txt
data:       ; python -m data_gen.generate
mappings:   ; python scripts/bootstrap_mappings.py
test:       ; python -m pytest tests -q
raw:        ; python -m pipeline --out outputs/raw_run --llm off || true      # expected: BLOCKED (exit 3)
final:      ; python -m pipeline --out outputs/corrected_run --corrections data/resubmissions.yaml
app:        ; streamlit run app.py
evaluate:   ; python evaluate.py && python scripts/build_readme.py
readme:     ; python scripts/build_readme.py
all: data mappings test raw final evaluate
