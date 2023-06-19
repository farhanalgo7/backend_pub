# -*- coding: utf-8 -*-
"""Stock-Ingestion.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1LelztqOHMENlKLm3Zpamu-mxnkSYSjHO
"""

#Prerequisites
#!pip install yfinance
#!pip install pandas
#p!ip install PyMySQL
#!pip install boto3

## importing dependencies
import pandas as pd     # for dataframe and csv file
import yfinance as yf   # for stock data 
import boto3
import mysql.connector
from datetime import datetime, date, timedelta
import pytz
import boto3
import logging
from boto3.dynamodb.conditions import Key , Attr
import os 
from ast import literal_eval
import json
# import config
from pandas_datareader import data
import time
import http.client

conn = http.client.HTTPSConnection("latest-stock-price.p.rapidapi.com")

headers = {
    'content-type': "application/octet-stream",
    'X-RapidAPI-Key': "7002bc0639msh1f55a52499f75dap1bb401jsn8467bea83c3a",
    'X-RapidAPI-Host': "latest-stock-price.p.rapidapi.com"
}

print(conn)

def get_secret():

    secret_name = "FABRIC-RDS-Secret-Keys"
    region_name = "ap-south-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager',region_name=region_name)
    # client = session.client(service_name='secretsmanager',region_name=region_name,aws_access_key_id=config.algo_access_key, aws_secret_access_key=config.algo_secret_access_token)

    get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    return get_secret_value_response

credentials = json.loads(get_secret()['SecretString'])
# print(credentials)
# 
# connecting to dynamodb Config table to get list of available ticker ids
algoDDB= boto3.resource('dynamodb',region_name=credentials['region_name'], endpoint_url='http://dynamodb.ap-south-1.amazonaws.com')
# algoDDB= boto3.resource('dynamodb',endpoint_url='http://dynamodb.ap-south-1.amazonaws.com',aws_access_key_id=config.algo_access_key, aws_secret_access_key=config.algo_secret_access_token,region_name=config.region_name)
list(algoDDB.tables.all())

rds_client = boto3.client("rds", region_name = credentials["region_name"])
# rds_client = boto3.client("rds", region_name = credentials["region_name"],aws_access_key_id=config.algo_access_key, aws_secret_access_key=config.algo_secret_access_token)
os.environ["LIBMYSQL_ENABLE_CLEARTEXT_PLUGIN"] = "1"
host=credentials['host']

token = rds_client.generate_db_auth_token(DBHostname = host, Port = credentials['port'], DBUsername = credentials['username'], Region = credentials['region_name'])

config_table = algoDDB.Table('ConfigTable')
list_ticker_ids=[]
res =  config_table.scan()

for item in res['Items']:
    list_ticker_ids.append(item['Stock_Ticker_Symbol'])
    # print( item['Stock_Ticker_Symbol'], item['Ticker_Name'] )

# logging.info("Available ticker id's : ",list_ticker_ids)
print("Available ticker id's : ",list_ticker_ids)

#def get_connection(): 
#  username= credentials["username"]

#  return mysql.connector.connect(host=host , user=username , password=token)
def get_connection():
    host = 'fabric-database-1.cptxszv3ahgy.ap-south-1.rds.amazonaws.com'
    # username = 'akangane'
    # token = 'Unch@rted29'
    #db_name = 'your_db_name'

    return mysql.connector.connect(host=host, user=credentials['username'], password=token,buffered=True)

def crawl_stock(list_ticker_ids , frequency , database , table):  

  # connect to the database
    try:
        db= get_connection()
        print("Connection Succeeded.")
    except Exception as e: 
      print('Unable to connect DB Instance , got error ' + e)
      return 0

    # set up a cursor
    cursor = db.cursor()

    # create the ingestion table if it does not exist
   #create_table_query = "CREATE TABLE IF NOT EXISTS {} (ticker_id VARCHAR(20), date DATE, open FLOAT, high FLOAT, low FLOAT, close FLOAT, volume INT, PRIMARY KEY (ticker_id, date));".format(ingestion_table_name)
    query="use "+database
    cursor.execute(query)
    
    # Initializing the table_columns
    table_Columns = literal_eval(credentials["columns"])
    cols = ",".join([str(i) for i in table_Columns])
    error_tickers=[]
    IST = pytz.timezone('Asia/Kolkata')
    # Initializing the table_columns
    for ticker in list_ticker_ids:
        
        try:
            
            #stock_data will store data about each company
           
            print('Downloading using Yfinance...')
            print(ticker)
            ## intializing from time which will be current time - 'frequency' hour(s)
            #from_time = datetime.now(IST) - timedelta(hours= frequency)
            # getting stock data for last 'frequency' hours
            stock_data = yf.download( ticker, start = datetime.now(IST).strftime('%Y-%m-%d') , end= datetime.now(IST)).reset_index()
            # print(stock_data)
            if stock_data.empty:
                print("Unable to fetch data from yfinance.")
                try:
                    # 
                    #   print("Retrying using Pandas Datareader library")
                    # stock_data = data.DataReader(ticker, 'yahoo', datetime.now(IST).strftime('%Y-%m-%d')).reset_index()
                    
                    # if stock_data.empty: 
                    print("Retrying using RapidApi")
                    conn.request("GET", "/price?Indices=NIFTY%20200&Identifier="+ticker.split('.')[0]+"EQN", headers=headers)
                    time.sleep(2)
                    

                    res = conn.getresponse()
                    time.sleep(2)
                    data = res.read()
                    
                    data=data.decode('UTF-8')
                    data = json.loads(data)
                    print("new api output",data)
                    if len(data)==0:
                        error_tickers.append(ticker)
                        print("Error+++++++",ticker)
                        
                        
                except Exception as ex:
                    print(f"Unable to fetch stock data for {ticker}: {ex}")

        except Exception as e:
          print(e)
          
        # stock_data = yf.download( ticker, start = datetime(2022, 11, 17, 0,0,0,0).strftime('%Y-%m-%d') , end= datetime(2022, 11, 24, 0,0,0,0).strftime('%Y-%m-%d')).reset_index()
        print("----------")
        print(stock_data)
        # print(stock_data.empty)
        print("----------")
            #******************************** Writing data to table ************************************************
            ### prepare a query
        query= "Insert  into " +table+ " (" +cols + ") VALUES (%s ,%s , %s , %s , %s , %s , %s , %s) "
            ### inserting to database 
        try:
            
                
            if stock_data.empty:
                cursor.execute(query, (ticker, datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S') ,data[0]['open'],data[0]['dayHigh'],data[0]['dayLow'],data[0]['lastPrice'],data[0]['lastPrice'],float(data[0]['totalTradedVolume'])))
                db.commit()
                print("*******************Data entered successfully new_api***********************")
                
            else:
                cursor.execute(query, (ticker, datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S') ,stock_data['Open'][0],stock_data['High'][0],stock_data['Low'][0],stock_data['Close'][0],stock_data['Adj Close'][0],float(stock_data['Volume'][0])))
                db.commit()
                print("*******************Data entered successfully***********************")
            
        except Exception as e: 
            print('Error occured on writing to table :',e)
            db.commit()
    
    # closing connections
    cursor.close() 
    db.close()
    print("Tickers with errors->",error_tickers)

#list_ticker_ids= ['TCS.NS' , 'WIPRO.NS' ,'INFY.NS' ,'HCLTECH.NS' , 'TECHM.NS' , 'MINDTREE.NS' ,'COFORGE.NS']
crawl_stock( list_ticker_ids , 1 , credentials["Database_Name"] , credentials['Ingestion_table_name']) #calling the main function




