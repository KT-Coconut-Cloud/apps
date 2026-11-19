-- Athena table over the clean bucket. Replace <CLEAN_BUCKET> and run once.
-- run_id uses partition projection, so new runs need no ALTER TABLE or crawler.
-- Columns follow the export file.

CREATE EXTERNAL TABLE IF NOT EXISTS livelihood_payment (
  payment_token      string,
  household_token    string,
  region             string,
  age_group          string,
  gender             string,
  pay_month          string,
  benefit_type       string,
  household_size     string,
  income_ratio_band  string
)
PARTITIONED BY (run_id string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
LOCATION 's3://<CLEAN_BUCKET>/data/livelihood_payment/'
TBLPROPERTIES (
  'skip.header.line.count' = '1',
  'projection.enabled' = 'true',
  'projection.run_id.type' = 'injected',
  'storage.location.template' = 's3://<CLEAN_BUCKET>/data/livelihood_payment/run_id=${run_id}/'
);
