#!/usr/bin/python3

import psycopg2
import sqlalchemy
import os
import datetime
import zipfile
import io
import json

def remove_nulls(s):
    if s is None:
        return None
    else:
        return s.replace('\x00','\\x00')

def batch(iterable, n=1):
    l = len(iterable)
    for ndx in range(0, l, n):
        yield iterable[ndx:min(ndx + n, l)]

def _bulk_insert_sql(table, rows):
    if not rows:
        raise ValueError('Must be at least one dictionary in the rows variable')
    else:
        keys = set(rows[0].keys())
        for row in rows:
            if set(row.keys()) != keys:
                raise ValueError('All dictionaries must contain the same keys')

    # Notice we removed ON CONFLICT DO NOTHING!
    sql = (f'''
    INSERT INTO {table}
        ('''
        +
        ','.join(keys)
        +
        ''')
        VALUES
        '''
        +
        ','.join([ '('+','.join([f':{key}{i}' for key in keys])+')' for i in range(len(rows))])
        )

    binds = { key+str(i):value for i,row in enumerate(rows) for key,value in row.items() }
    return (' '.join(sql.split()), binds)


def bulk_insert(connection, table, rows):
    if len(rows)==0:
        return
    sql, binds = _bulk_insert_sql(table, rows)
    res = connection.execute(sqlalchemy.sql.text(sql), binds)


def insert_tweets(connection, tweets, batch_size=1000):
    for i,tweet_batch in enumerate(batch(tweets, batch_size)):
        print(datetime.datetime.now(),'insert_tweets i=',i)
        _insert_tweets(connection, tweet_batch)


def _insert_tweets(connection,input_tweets):
    users = []
    tweets = []
    users_unhydrated_from_tweets = []
    users_unhydrated_from_mentions = []
    tweet_mentions = []
    tweet_tags = []
    tweet_media = []
    tweet_urls = []

    for tweet in input_tweets:
        # Instead of getting an ID, we just grab the raw URL string
        user_url = tweet['user']['url'] if tweet['user']['url'] is not None else None

        users.append({
            'id_users':tweet['user']['id'],
            'created_at':tweet['user']['created_at'],
            'updated_at':tweet['created_at'],
            'screen_name':remove_nulls(tweet['user']['screen_name']),
            'name':remove_nulls(tweet['user']['name']),
            'location':remove_nulls(tweet['user']['location']),
            'url':user_url,
            'description':remove_nulls(tweet['user']['description']),
            'protected':tweet['user']['protected'],
            'verified':tweet['user']['verified'],
            'friends_count':tweet['user']['friends_count'],
            'listed_count':tweet['user']['listed_count'],
            'favourites_count':tweet['user']['favourites_count'],
            'statuses_count':tweet['user']['statuses_count'],
            'withheld_in_countries':tweet['user'].get('withheld_in_countries',None),
            })

        try:
            geo_coords = tweet['geo']['coordinates']
            geo_coords = str(tweet['geo']['coordinates'][0]) + ' ' + str(tweet['geo']['coordinates'][1])
            geo_str = 'POINT'
        except TypeError:
            try:
                geo_coords = '('
                for i,poly in enumerate(tweet['place']['bounding_box']['coordinates']):
                    if i>0:
                        geo_coords+=','
                    geo_coords+='('
                    for j,point in enumerate(poly):
                        geo_coords+= str(point[0]) + ' ' + str(point[1]) + ','
                    geo_coords+= str(poly[0][0]) + ' ' + str(poly[0][1])
                    geo_coords+=')'
                geo_coords+=')'
                geo_str = 'MULTIPOLYGON'
            except KeyError:
                if tweet['user']['geo_enabled']:
                    geo_str = None
                    geo_coords = None

        try:
            text = tweet['extended_tweet']['full_text']
        except:
            text = tweet['text']

        try:
            country_code = tweet['place']['country_code'].lower()
        except TypeError:
            country_code = None

        if country_code == 'us':
            state_code = tweet['place']['full_name'].split(',')[-1].strip().lower()
            if len(state_code)>2:
                state_code = None
        else:
            state_code = None

        try:
            place_name = tweet['place']['full_name']
        except TypeError:
            place_name = None

        if tweet.get('in_reply_to_user_id',None) is not None:
            users_unhydrated_from_tweets.append({
                'id_users':tweet['in_reply_to_user_id'],
                'screen_name':tweet.get('in_reply_to_screen_name', None),
                })

        tweets.append({
            'id_tweets':tweet['id'],
            'id_users':tweet['user']['id'],
            'created_at':tweet['created_at'],
            'in_reply_to_status_id':tweet.get('in_reply_to_status_id',None),
            'in_reply_to_user_id':tweet.get('in_reply_to_user_id',None),
            'quoted_status_id':tweet.get('quoted_status_id',None),
            'geo_coords':geo_coords,
            'geo_str':geo_str,
            'retweet_count':tweet.get('retweet_count',None),
            'quote_count':tweet.get('quote_count',None),
            'favorite_count':tweet.get('favorite_count',None),
            'withheld_copyright':tweet.get('withheld_copyright',None),
            'withheld_in_countries':tweet.get('withheld_in_countries',None),
            'place_name':place_name,
            'country_code':country_code,
            'state_code':state_code,
            'lang':tweet.get('lang'),
            'text':remove_nulls(text),
            'source':remove_nulls(tweet.get('source',None)),
            })

        try:
            urls = tweet['extended_tweet']['entities']['urls']
        except KeyError:
            urls = tweet['entities']['urls']

        for url in urls:
            tweet_urls.append({
                'id_tweets':tweet['id'],
                'url':url['expanded_url'],
                })

        try:
            mentions = tweet['extended_tweet']['entities']['user_mentions']
        except KeyError:
            mentions = tweet['entities']['user_mentions']

        for mention in mentions:
            users_unhydrated_from_mentions.append({
                'id_users':mention['id'],
                'name':remove_nulls(mention.get('name', None)),
                'screen_name':remove_nulls(mention.get('screen_name', None)),
                })

            tweet_mentions.append({
                'id_tweets':tweet['id'],
                'id_users':mention['id']
                })

        try:
            hashtags = tweet['extended_tweet']['entities']['hashtags']
            cashtags = tweet['extended_tweet']['entities']['symbols']
        except KeyError:
            hashtags = tweet['entities']['hashtags']
            cashtags = tweet['entities']['symbols']

        tags = [ '#'+hashtag['text'] for hashtag in hashtags ] + [ '$'+cashtag['text'] for cashtag in cashtags ]

        for tag in tags:
            tweet_tags.append({
                'id_tweets':tweet['id'],
                'tag':remove_nulls(tag)
                })

        try:
            media = tweet['extended_tweet']['extended_entities']['media']
        except KeyError:
            try:
                media = tweet['extended_entities']['media']
            except KeyError:
                media = []

        for medium in media:
            tweet_media.append({
                'id_tweets':tweet['id'],
                'url':medium['media_url'],
                'type':medium['type']
                })

    with connection.begin() as trans:
        bulk_insert(connection, 'users', users)
        bulk_insert(connection, 'users', users_unhydrated_from_tweets)
        bulk_insert(connection, 'users', users_unhydrated_from_mentions)
        bulk_insert(connection, 'tweet_mentions', tweet_mentions)
        bulk_insert(connection, 'tweet_tags', tweet_tags)
        bulk_insert(connection, 'tweet_media', tweet_media)
        bulk_insert(connection, 'tweet_urls', tweet_urls)

        if len(tweets) > 0:
            # Notice we removed ON CONFLICT DO NOTHING!
            sql = sqlalchemy.sql.text('''
            INSERT INTO tweets
                (id_tweets,id_users,created_at,in_reply_to_status_id,in_reply_to_user_id,quoted_status_id,geo,retweet_count,quote_count,favorite_count,withheld_copyright,withheld_in_countries,place_name,country_code,state_code,lang,text,source)
                VALUES
                '''
                +
                ','.join([f"(:id_tweets{i},:id_users{i},:created_at{i},:in_reply_to_status_id{i},:in_reply_to_user_id{i},:quoted_status_id{i},ST_GeomFromText(:geo_str{i} || '(' || :geo_coords{i} || ')'), :retweet_count{i},:quote_count{i},:favorite_count{i},:withheld_copyright{i},:withheld_in_countries{i},:place_name{i},:country_code{i},:state_code{i},:lang{i},:text{i},:source{i})" for i in range(len(tweets))])
                )
            res = connection.execute(sql, { key+str(i):value for i,tweet in enumerate(tweets) for key,value in tweet.items() })


if __name__ == '__main__':

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',required=True)
    parser.add_argument('--inputs',nargs='+',required=True)
    parser.add_argument('--batch_size',type=int,default=1000)
    args = parser.parse_args()

    engine = sqlalchemy.create_engine(args.db, connect_args={
        'application_name': 'load_tweets.py --inputs '+' '.join(args.inputs),
        })
    connection = engine.connect()

    for filename in sorted(args.inputs, reverse=True):
        with zipfile.ZipFile(filename, 'r') as archive:
            print(datetime.datetime.now(),filename)
            for subfilename in sorted(archive.namelist(), reverse=True):
                with io.TextIOWrapper(archive.open(subfilename)) as f:
                    tweets = []
                    for i,line in enumerate(f):
                        tweet = json.loads(line)
                        tweets.append(tweet)
                    insert_tweets(connection,tweets,args.batch_size)
