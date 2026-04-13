#!/bin/sh

echo '================================================================================'
echo 'load pg_denormalized'
echo '================================================================================'
time ls data/* | parallel sh load_denormalized.sh {}

echo '================================================================================'
echo 'load pg_normalized'
echo '================================================================================'
time ls data/* | parallel python3 load_tweets.py --db=postgresql://postgres:pass@localhost:20002/postgres --inputs={}

echo '================================================================================'
echo 'load pg_normalized_batch'
echo '================================================================================'
time ls data/* | parallel python3 -u load_tweets_batch.py --db=postgresql://postgres:pass@localhost:20003/postgres --inputs={}
