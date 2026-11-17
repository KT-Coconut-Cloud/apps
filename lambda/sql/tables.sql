-- Athena tables over the clean bucket. Replace <CLEAN_BUCKET> and run once per table.
-- run_id uses partition projection, so new runs need no ALTER TABLE or crawler.

CREATE EXTERNAL TABLE IF NOT EXISTS citizen (
  citizen_id     string,
  sigungu        string,
  household_type string
)
PARTITIONED BY (run_id string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
LOCATION 's3://<CLEAN_BUCKET>/data/citizen/'
TBLPROPERTIES (
  'skip.header.line.count' = '1',
  'projection.enabled' = 'true',
  'projection.run_id.type' = 'injected',
  'storage.location.template' = 's3://<CLEAN_BUCKET>/data/citizen/run_id=${run_id}/'
);

CREATE EXTERNAL TABLE IF NOT EXISTS crisis_signal (
  citizen_id   string,
  signal_month string,
  crisis_type  string,
  linked       string
)
PARTITIONED BY (run_id string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
LOCATION 's3://<CLEAN_BUCKET>/data/crisis_signal/'
TBLPROPERTIES (
  'skip.header.line.count' = '1',
  'projection.enabled' = 'true',
  'projection.run_id.type' = 'injected',
  'storage.location.template' = 's3://<CLEAN_BUCKET>/data/crisis_signal/run_id=${run_id}/'
);

CREATE EXTERNAL TABLE IF NOT EXISTS benefit_payment (
  citizen_id     string,
  year           string,
  benefit_type   string,
  monthly_amount string
)
PARTITIONED BY (run_id string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.OpenCSVSerde'
LOCATION 's3://<CLEAN_BUCKET>/data/benefit_payment/'
TBLPROPERTIES (
  'skip.header.line.count' = '1',
  'projection.enabled' = 'true',
  'projection.run_id.type' = 'injected',
  'storage.location.template' = 's3://<CLEAN_BUCKET>/data/benefit_payment/run_id=${run_id}/'
);
