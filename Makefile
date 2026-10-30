.PHONY: help setup test audit ingest clean align features baseline

help:
	@echo "PM2.5 Research Pipeline"
	@echo ""
	@echo "Targets:"
	@echo "  setup      Create conda environment"
	@echo "  test       Run tests"
	@echo "  audit      Run station audit (Stage 1)"
	@echo "  ingest     Download ground PM2.5 data (Stage 2)"
	@echo "  gee        Extract GEE data (Stage 2)"
	@echo "  clean      Clean raw data (Stage 4)"
	@echo "  align      Spatiotemporal alignment (Stage 4)"
	@echo "  features   Build feature set (Stage 4)"
	@echo "  baseline   Train baseline models (Stage 5)"

setup:
	conda env create -f environment.yml

test:
	pytest tests/ -v

audit:
	python -m src.ingest.fetch_xkdr_stations
	python -m src.ingest.fetch_openaq_stations
	python -m src.ingest.merge_stations
	python -m src.ingest.completeness_audit
	python -m src.ingest.generate_audit_report

ingest:
	python -m src.ingest.ingest_pm25

gee:
	python -m src.ingest.gee_extract --dataset s5p_no2
	python -m src.ingest.gee_extract --dataset s5p_co
	python -m src.ingest.gee_extract --dataset s5p_so2
	python -m src.ingest.gee_extract --dataset s5p_hcho
	python -m src.ingest.gee_extract --dataset s5p_aer_ai
	python -m src.ingest.gee_extract --dataset maiac_aod
	python -m src.ingest.gee_extract --dataset era5_land
	python -m src.ingest.gee_extract --dataset era5_blh
	python -m src.ingest.gee_extract --dataset cams_aod
