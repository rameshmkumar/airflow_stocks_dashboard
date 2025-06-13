from __future__ import annotations

import pendulum
import logging
import os
import pandas as pd
import yfinance as yf

from airflow.models.dag import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator
from datetime import datetime

STOCK_LIST_ALL=['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'JPM', 'V', 'JNJ', 'XOM']
HISTORICAL_DATA_PERIOD="1y"

log=logging.getLogger(__name__)


def fetch_stock_data(stock_list: list[str], period:str, ti):
    all_data=[]
    for stock in stock_list:
        try:
            stock_data=yf.Ticker(stock)
            hist_df=stock_data.history(period=period, interval="1d", auto_adjust=True, prepost=False)

            if hist_df.empty:
                log.warning(f"No data returned for {stock} for period {period}")
                continue

            hist_df['ticker']= stock  #created a new column with the ticker symbol
            hist_df.reset_index(inplace=True)  #reseting the index that came from the yfinance

            #Removing the timezone from the Date
            if 'Date' in hist_df.columns:
                hist_df['timestamp_utc']=pd.to_datetime(hist_df['Date']).dt.tz_localize(None)   #Creating a new column as timestamp
                hist_df.drop(columns=['Date'], inplace=True)              #removing the original date column

            elif 'Datetime' in hist_df.columns:
                hist_df['timestamp_utc']=pd.to_datetime(hist_df['Datetime']).dt.tz_localize(None)   
                hist_df.drop(columns=['Datetime'], inplace=True)              
            
            else:
                log.warning(f"Couldn't find the 'Date' or 'Datetime' column for {stock}")

            columns_to_keep={'timestamp_utc':'timestamp_utc',
                             'Open':'open_price',
                             'High':'high_price',
                             'Low':'low_price',
                             'Close':'close_price',
                             'Volume':'volume',
                             'ticker':'ticker_symbol',
                             }
            
            existing_cols={k:v for k,v in columns_to_keep.items() if k in hist_df.columns}  #From the column names to keep we filter the columns that are there in hist_df
            hist_df_selected=hist_df[list(existing_cols.keys())].rename(columns=existing_cols)   #Filtered the Dataframe with only the existing cols and then renamed usinng dict parameter

            all_data.append(hist_df_selected)
            log.info(f"Successfully fetched and processed {len(hist_df_selected)} record")

        except Exception as e:
            log.error(f"Error while fetching  the stocks data {e}")
        
    if not all_data:
        ti.xcom_push(key="stock_data_json", value="[]")
        return []
        
    final_df=pd.concat(all_data, ignore_index=True)  #removing the index for better concat

    json_data=final_df.to_json(orient="records", date_format="iso")
    ti.xcom_push(key="stock_data_json", value=json_data)

    return json_data
    
default_args={'owner':'airflow',
              'depends_on_past': False,
              'email_on_failure':False,
              'email_on_retry':False,
              'retries':1,
              'retry_delay': pendulum.duration(minutes=2),
              }

with DAG(
    dag_id='stock_data_ingestion_pipeline_v1',
    default_args=default_args,
    description='Pipeline to fetch stock data',
    schedule='@daily',
    start_date=pendulum.datetime(2024,1,1, tz="utc"),
    catchup=False,
    tags=['stocks', 'fetch'],
) as dag:
    
    start_pipeline=EmptyOperator(
        task_id='start_pipeline_marker'
    )

    #Task-1
    task_fetch_stock_data=PythonOperator(
        task_id='fetch_historical_stock_data',
        python_callable=fetch_stock_data,
        op_kwargs={
            'stock_list' : STOCK_LIST_ALL,
            'period' : HISTORICAL_DATA_PERIOD
        },
    )

    #placeholder for load
    task_load_to_timescaledb=EmptyOperator(
        task_id='load_data_to_timescaledb',
    )

    end_pipeline=EmptyOperator(
        task_id='end_pipeline_marker'
    )

    start_pipeline >> task_fetch_stock_data >>task_load_to_timescaledb >> end_pipeline
