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
from io import StringIO

from sqlalchemy import create_engine, text


STOCK_LIST_ALL=['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'JPM', 'V', 'JNJ', 'XOM']
HISTORICAL_DATA_PERIOD="1y"

TIMESCALE_USER_ENV=os.getenv('TIMESCALE_USER', 'admin')
TIMESCALE_PASSWORD_ENV=os.getenv('TIMESCALE_PASSWORD', 'admin')
TIMESCALE_DB_ENV=os.getenv('TIMESCALE_DB', 'stockdb')
TIMESCALE_HOST_ENV=os.getenv('TIMESCALE_HOST', 'timescaledb_stocks')
TIMESCALE_PORT_ENV=os.getenv('TIMESCALE_PORT', '5432')
TIMESCALE_TABLE_NAME="stocks_prices_historical"


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

def load_data_to_timescale_db(ti, db_user, db_password, db_host, db_port, db_name, table_name):
    
    stock_data_json=ti.xcom_pull(task_ids="fetch_historical_stock_data", key="stock_data_json")

    if not stock_data_json or stock_data_json =="[]":
        return "No new data to load"

    try:
        df=pd.read_json(StringIO(stock_data_json), orient="records")
        if 'timestamp_utc' in df.columns:
            df['timestamp_utc']=pd.to_datetime(df['timestamp_utc'],errors='coerce')  #Converting timestamps to datatime
            df.dropna(subset=['timestamp_utc'],inplace=True)      #Removing  the nan/missing values
        log.info(f"Successfully converted JSON from XComs to DataFrame. Shape:{df.shape}")
    
    except Exception as e:
        log.error(f"Failed to convert JSON from XComs to Dataframe:{e}")
        raise

    if df.empty:
        log.warning("DataFrame is empty after JSON conversion. ")
        return "DF empty after json conversion"
    
    DATABASE_URL=f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    try:
        engine=create_engine(DATABASE_URL)
        log.info(f"Loading {len(df)} rows into staging table '{table_name}_stagging'")
        
        staging_table_name = f"{table_name}_staging"

        df.to_sql(
            name=staging_table_name,
            con=engine,
            if_exists='replace',
            index=False,
            method='multi'
        )

        with engine.connect() as connection:

            cols_dtypes={
                'timestamp_utc':'TIMESTAMPTZ',
                'open_price':'DOUBLE PRECISION',
                'high_price':'DOUBLE PRECISION',
                'low_price':'DOUBLE PRECISION',
                'close_price':'DOUBLE PRECISION',
                'volume':'BIGINT',
                'ticker_symbol':'TEXT'
            }
            
            #creating the column name and their dtypes/default dtype
            sql_cols_str=",\n".join([f'"{col}" {cols_dtypes.get(col,
                            "TEXT")}' for col in df.columns if col in cols_dtypes])
            
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                {sql_cols_str}, 
                PRIMARY KEY (ticker_symbol, timestamp_utc) 
                );
            """
            connection.execute(text(create_table_sql))


            is_hypertable_check = text(f""" 
                SELECT EXISTS (
                    SELECT 1 FROM timescaledb_information.hypertables
                    WHERE hypertable_name = '{table_name}'    
                );
            """)

            is_hyper=connection.execute(is_hypertable_check).scalar_one_or_none()   #scalar_one_or_none() directly returs the sresult rather than as an object

            if not is_hyper:
                log.info(f"Table '{table_name}' is not a hypertable.")


                #sql query to create the timescaleDB
                create_hypertable_sql= text(f"""SELECT
                                            create_hypertable('{table_name}', 'timestamp_utc', if_not_exists => TRUE,
                                            migrate_data => TRUE);""")
                
                connection.execute(create_hypertable_sql)
                log.info(f"Successfully converted '{table_name}' to a hypertable on 'timestamp_utc'. ")

            else:
                log.info(f"Table '{table_name}' is already a hypertable")
            
            #ignoring duplicates
            insert_sql = f"""
            INSERT INTO {table_name} ({', '.join([f'"{col}"' for col in df.columns])})
            SELECT {', '.join([f'"{col}"' for col in df.columns])}
            FROM {staging_table_name}
            ON CONFLICT (ticker_symbol, timestamp_utc) DO NOTHING; 
            """

            result = connection.execute(text(insert_sql))
            log.info(f"Upserted {result.rowcount} rows from staging to '{table_name}'.")

            connection.execute(text(f"DROP TABLE {staging_table_name};"))
            log.info(f"Dropped the staging table {staging_table_name} from postgresql")
            
        
        return f"Data loaded into {table_name}."

    except Exception as e:
        log.error(f"Error loading the data into TimescaleDB: {e}")
        raise
    

default_args={'owner':'airflow',
              'depends_on_past': False,
              'email_on_failure':False,
              'email_on_retry':False,
              'retries':1,
              'retry_delay': pendulum.duration(minutes=2),
              }

with DAG(
    dag_id='stock_data_ingestion_pipeline_v2',
    default_args=default_args,
    description='Pipeline to fetch stock data, load to TimesacaleDB',
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
    task_load_to_timescaledb=PythonOperator(
        task_id='load_data_to_timescaledb',
        python_callable=load_data_to_timescale_db,
        op_kwargs={
            'db_user':TIMESCALE_USER_ENV,
            'db_password': TIMESCALE_PASSWORD_ENV,
            'db_host': TIMESCALE_HOST_ENV,
            'db_port': TIMESCALE_PORT_ENV,
            'db_name': TIMESCALE_DB_ENV,
            'table_name': TIMESCALE_TABLE_NAME,
        }
    )

    end_pipeline=EmptyOperator(
        task_id='end_pipeline_marker'
    )

    start_pipeline >> task_fetch_stock_data >>task_load_to_timescaledb >> end_pipeline
