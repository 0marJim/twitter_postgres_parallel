#!/bin/bash

files=$(find data/*)

echo '================================================================================'
echo 'load pg_denormalized'
echo '================================================================================'
# The quotes are tricky here, so we carefully escape the \ characters for the COPY command
time echo "$files" | parallel "unzip -p {} | sed 's/\\\\u0000//g' | psql postgresql://postgres:pass@localhost:20001/postgres -c \"COPY tweets_jsonb (data) FROM STDIN csv quote e'\\x01' delimiter e'\\x02';\""

echo '================================================================================'
echo 'load pg_normalized'
echo '================================================================================'
time echo "$files" | parallel 'python3 load_tweets.py --db=postgresql://postgres:pass@localhost:20002/postgres --inputs={}'

echo '================================================================================'
echo 'load pg_normalized_batch'
echo '================================================================================'
time echo "$files" | parallel 'python3 -u load_tweets_batch.py --db=postgresql://postgres:pass@localhost:20003/postgres --inputs={}'
