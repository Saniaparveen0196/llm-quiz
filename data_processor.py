import requests
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
import io
import base64
import json
from bs4 import BeautifulSoup
import PyPDF2
from PIL import Image
import matplotlib.pyplot as plt
import seaborn as sns

class DataProcessor:
    """Handles data sourcing, preparation, analysis, and visualization"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def download_file(self, url: str, headers: Optional[Dict] = None) -> bytes:
        """Download a file from URL"""
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise Exception(f"Failed to download file: {str(e)}")
    
    def parse_pdf(self, pdf_content: bytes) -> Dict[str, Any]:
        """Extract text and tables from PDF"""
        try:
            pdf_file = io.BytesIO(pdf_content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text_content = []
            for page in pdf_reader.pages:
                text_content.append(page.extract_text())
            
            return {
                "text": "\n".join(text_content),
                "num_pages": len(pdf_reader.pages),
                "pages": text_content
            }
        except Exception as e:
            raise Exception(f"Failed to parse PDF: {str(e)}")
    
    def parse_csv(self, csv_content: bytes, encoding: str = 'utf-8') -> pd.DataFrame:
        """Parse CSV content into DataFrame"""
        try:
            # Try with header first
            df = pd.read_csv(io.BytesIO(csv_content), encoding=encoding)
            # Check if first column name is numeric (suggests no header)
            if len(df.columns) > 0 and str(df.columns[0]).isdigit():
                # Re-read without header
                df = pd.read_csv(io.BytesIO(csv_content), encoding=encoding, header=None)
            return df
        except:
            try:
                df = pd.read_csv(io.BytesIO(csv_content), encoding='latin-1')
                # Check if first column name is numeric (suggests no header)
                if len(df.columns) > 0 and str(df.columns[0]).isdigit():
                    df = pd.read_csv(io.BytesIO(csv_content), encoding='latin-1', header=None)
                return df
            except Exception as e:
                raise Exception(f"Failed to parse CSV: {str(e)}")
    
    def parse_excel(self, excel_content: bytes, sheet_name: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        """Parse Excel file into DataFrames"""
        try:
            excel_file = io.BytesIO(excel_content)
            return pd.read_excel(excel_file, sheet_name=sheet_name)
        except Exception as e:
            raise Exception(f"Failed to parse Excel: {str(e)}")
    
    def parse_json(self, json_content: bytes) -> Any:
        """Parse JSON content"""
        try:
            return json.loads(json_content.decode('utf-8'))
        except Exception as e:
            raise Exception(f"Failed to parse JSON: {str(e)}")
    
    def parse_html(self, html_content: str) -> BeautifulSoup:
        """Parse HTML content"""
        return BeautifulSoup(html_content, 'html.parser')
    
    def analyze_dataframe(self, df: pd.DataFrame, operation: str, **kwargs) -> Any:
        """Perform analysis operations on DataFrame"""
        operation = operation.lower()
        
        if operation == "sum":
            column = kwargs.get("column")
            if column and column in df.columns:
                return float(df[column].sum())
            else:
                # Sum all numeric columns
                numeric_df = df.select_dtypes(include=[float, int])
                return float(numeric_df.sum().sum())
        elif operation == "mean" or operation == "average":
            column = kwargs.get("column")
            if column and column in df.columns:
                return float(df[column].mean())
        elif operation == "count":
            return len(df)
        elif operation == "max":
            column = kwargs.get("column")
            if column and column in df.columns:
                return df[column].max()
        elif operation == "min":
            column = kwargs.get("column")
            if column and column in df.columns:
                return df[column].min()
        elif operation == "filter":
            # kwargs should contain filter conditions
            filtered_df = df.copy()
            for key, value in kwargs.items():
                if key != "operation" and key in df.columns:
                    filtered_df = filtered_df[filtered_df[key] == value]
            return filtered_df
        
        return None
    
    def create_visualization(self, data: Any, chart_type: str, output_path: Optional[str] = None) -> str:
        """Create visualization and return as base64 encoded image"""
        plt.figure(figsize=(10, 6))
        
        if chart_type == "bar":
            if isinstance(data, pd.DataFrame):
                data.plot(kind='bar', ax=plt.gca())
            else:
                plt.bar(range(len(data)), data)
        elif chart_type == "line":
            if isinstance(data, pd.DataFrame):
                data.plot(kind='line', ax=plt.gca())
            else:
                plt.plot(data)
        elif chart_type == "scatter":
            if isinstance(data, pd.DataFrame):
                x_col = data.columns[0]
                y_col = data.columns[1] if len(data.columns) > 1 else data.columns[0]
                plt.scatter(data[x_col], data[y_col])
        elif chart_type == "histogram":
            if isinstance(data, pd.DataFrame):
                data.hist(ax=plt.gca())
            else:
                plt.hist(data)
        
        plt.tight_layout()
        
        # Save to bytes
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png')
        img_buffer.seek(0)
        
        # Convert to base64
        img_base64 = base64.b64encode(img_buffer.read()).decode('utf-8')
        plt.close()
        
        return f"data:image/png;base64,{img_base64}"
    
    def extract_table_from_text(self, text: str) -> Optional[pd.DataFrame]:
        """Try to extract table from text"""
        lines = text.split('\n')
        table_data = []
        for line in lines:
            # Try to split by common delimiters
            if '\t' in line:
                table_data.append(line.split('\t'))
            elif '|' in line:
                table_data.append([cell.strip() for cell in line.split('|') if cell.strip()])
            elif ',' in line and len(line.split(',')) > 2:
                table_data.append(line.split(','))
        
        if table_data:
            try:
                return pd.DataFrame(table_data[1:], columns=table_data[0] if table_data else None)
            except:
                pass
        
        return None