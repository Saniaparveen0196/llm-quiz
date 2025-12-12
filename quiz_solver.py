import asyncio
from playwright.async_api import async_playwright, Browser, Page
from typing import Dict, Any, Optional, List
import re
import json
import requests
from data_processor import DataProcessor
from llm_client import GroqClient
from config import Config
import time
from PIL import Image
from collections import Counter
import io
import pandas as pd

class QuizSolver:
    """Solves quiz tasks using LLM and data processing"""
    
    def __init__(self, api_key: str):
        self.data_processor = DataProcessor()
        self.llm_client = GroqClient(api_key)
        self.browser: Optional[Browser] = None
        self.playwright = None
    
    async def initialize_browser(self):
        """Initialize headless browser"""
        if self.browser is None:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
    
    async def close_browser(self):
        """Close browser and playwright"""
        try:
            if self.browser:
                await self.browser.close()
                self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
        except Exception as e:
            print(f"Error closing browser: {e}")
    
    async def fetch_quiz_page(self, url: str) -> Dict[str, Any]:
        """Fetch and parse quiz page"""
        await self.initialize_browser()
        page = await self.browser.new_page()
        
        try:
            await page.goto(url, wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(3000)
            
            try:
                result_div = await page.query_selector('#result')
                if result_div:
                    await page.wait_for_timeout(1000)
            except:
                pass
            
            content = await page.content()
            question_text = await self._extract_question(page, content)
            submit_url = await self._extract_submit_url(page, content, question_text, url)
            
            if not submit_url and '/project2' in url:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                submit_url = f"{parsed.scheme}://{parsed.netloc}/submit"
                print(f"Using fixed submit URL for /project2: {submit_url}")
            
            if submit_url and not submit_url.startswith('http'):
                from urllib.parse import urljoin
                submit_url = urljoin(url, submit_url)
            
            return {
                "question": question_text,
                "submit_url": submit_url,
                "html": content,
                "url": url
            }
        finally:
            await page.close()
    
    async def _extract_question(self, page: Page, html: str) -> str:
        """Extract question text from page"""
        question_text = ""
        
        try:
            result_div = await page.query_selector('#result')
            if result_div:
                inner_html = await result_div.evaluate('el => el.innerHTML')
                if inner_html:
                    question_text = await result_div.inner_text()
                    if not question_text or len(question_text) < 10:
                        question_text = inner_html
        except:
            pass
        
        if not question_text or len(question_text) < 20:
            try:
                script_content = await page.evaluate(r"""
                    () => {
                        const scripts = Array.from(document.querySelectorAll('script'));
                        for (const script of scripts) {
                            const text = script.textContent || script.innerHTML;
                            if (text.includes('atob')) {
                                try {
                                    const patterns = [
                                        /atob\(['"`]([^'"`]+)['"`]\)/g,
                                        /atob\(['"`]([^'"`\n]+)['"`]\)/g
                                    ];
                                    for (const pattern of patterns) {
                                        const matches = text.matchAll(pattern);
                                        for (const match of matches) {
                                            if (match[1]) {
                                                try {
                                                    return atob(match[1]);
                                                } catch(e) {}
                                            }
                                        }
                                    }
                                } catch(e) {}
                            }
                        }
                        const result = document.querySelector('#result');
                        if (result && result.innerHTML) {
                            return result.innerHTML;
                        }
                        return null;
                    }
                """)
                if script_content:
                    question_text = script_content
            except Exception as e:
                print(f"Error extracting base64 content: {e}")
        
        if not question_text or len(question_text) < 10:
            selectors = ['.question', '.quiz-question', 'body']
            for selector in selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        if text and len(text) > 10:
                            question_text = text
                            break
                except:
                    continue
        
        if question_text:
            question_text = re.sub(r'<script[^>]*>.*?</script>', '', question_text, flags=re.DOTALL)
            question_text = re.sub(r'<br\s*/?>', '\n', question_text, flags=re.IGNORECASE)
            question_text = re.sub(r'<[^>]+>', '', question_text)
            question_text = ' '.join(question_text.split())
        
        return question_text
    
    async def _extract_submit_url(self, page: Page, html: str, question_text: str = "", base_url: str = "") -> Optional[str]:
        """Extract submit URL from page"""
        from urllib.parse import urljoin
        
        url_pattern = r'https?://[^\s<>"\'`]+/submit[^\s<>"\'`]*'
        relative_pattern = r'["\']?/submit[^\s<>"\'`]*["\']?'
        
        if question_text:
            matches = re.findall(url_pattern, question_text)
            if matches:
                return matches[0]
            
            rel_matches = re.findall(relative_pattern, question_text)
            if rel_matches:
                rel_url = rel_matches[0].strip('"\'')
                if base_url:
                    return urljoin(base_url, rel_url)
                return rel_url
        
        try:
            result_div = await page.query_selector('#result')
            if result_div:
                result_html = await result_div.evaluate('el => el.innerHTML')
                result_text = await result_div.inner_text()
                for text in [result_html, result_text]:
                    if text:
                        matches = re.findall(url_pattern, text)
                        if matches:
                            return matches[0]
        except:
            pass
        
        matches = re.findall(url_pattern, html)
        if matches:
            return matches[0]
        
        return None
    
    async def solve_quiz(self, quiz_data: Dict[str, Any]) -> Dict[str, Any]:
        """Solve a quiz question with enhanced handling"""
        question = quiz_data.get("question", "")
        
        if not question or len(question.strip()) < 10:
            print(f"Warning: Question text is too short or empty: '{question[:100]}'")
            return {
                "answer": None,
                "reasoning": "Question text not found or too short"
            }
        
        print(f"Question extracted: {question[:200]}...")
        
        # Parse question to identify task type
        task_info = self._parse_question_enhanced(question, quiz_data)
        print(f"Task info: {task_info}")
        
        # Handle special question types with direct processing
        answer = None
        
        # 1. Command strings (uv, git)
        if task_info.get("question_type") == "command":
            answer = self._extract_command_answer(question, task_info, quiz_data)
            if answer:
                return {"answer": answer, "reasoning": "Command extracted directly"}
        
        # 2. Markdown links
        if task_info.get("question_type") == "markdown_link":
            answer = self._extract_markdown_link(question)
            if answer:
                return {"answer": answer, "reasoning": "Markdown link extracted"}
        
        # 3. Image processing (dominant color)
        if task_info.get("data_type") == "image" and task_info.get("operation") == "dominant_color":
            answer = await self._process_image_color(task_info, quiz_data)
            if answer:
                return {"answer": answer, "reasoning": "Dominant color extracted from image"}
        
        # 4. CSV normalization
        if task_info.get("operation") == "normalize" and task_info.get("data_type") == "csv":
            answer = await self._process_csv_normalization(task_info, quiz_data)
            if answer:
                return {"answer": answer, "reasoning": "CSV normalized to JSON"}
        
        # 5. PDF invoice calculation
        if task_info.get("data_type") == "pdf_invoice":
            answer = await self._process_pdf_invoice(task_info, quiz_data)
            if answer:
                return {"answer": answer, "reasoning": "Invoice total calculated from PDF"}
        
        # 6. GitHub API processing
        if task_info.get("data_type") == "github_api":
            answer = await self._process_github_tree(task_info, quiz_data)
            if answer is not None:
                return {"answer": answer, "reasoning": "GitHub API response processed"}
        
        # 7. Audio transcription (requires Whisper API - fallback to LLM)
        if task_info.get("data_type") == "audio":
            print("⚠️ Audio transcription requires Whisper API - using LLM fallback")
            # Extract audio URL and pass to LLM with better context
            audio_url = await self._get_audio_url(task_info, quiz_data)
            if audio_url:
                context = {"audio_url": audio_url, "instructions": "Listen to the audio file and transcribe the spoken passphrase including the 3-digit code."}
                result = self.llm_client.solve_quiz(question, context)
                return {
                    "answer": result["answer"],
                    "reasoning": result["reasoning"]
                }
        
        # For all other cases, use existing data fetching + LLM logic
        context = {}
        if task_info.get("needs_data"):
            print("Fetching and processing data...")
            data_context = await self._fetch_and_process_data(task_info, quiz_data)
            context.update(data_context)
            print(f"Data context keys: {list(data_context.keys())}")
        
        if context.get("computed_result") is not None:
            print(f"Using computed result directly: {context['computed_result']}")
            return {
                "answer": context["computed_result"],
                "reasoning": f"Computed result: {context['computed_result']}"
            }
        
        # Use LLM for remaining cases
        print("Calling LLM to solve quiz...")
        try:
            result = self.llm_client.solve_quiz(question, context)
            print(f"LLM response - Answer: {result.get('answer')}, Reasoning length: {len(result.get('reasoning', ''))}")
        except Exception as e:
            print(f"Error calling LLM: {str(e)}")
            import traceback
            traceback.print_exc()
            result = {"answer": None, "reasoning": f"Error: {str(e)}"}
        
        return {
            "answer": result["answer"],
            "reasoning": result["reasoning"]
        }
    
    def _parse_question_enhanced(self, question: str, quiz_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced question parsing"""
        question_lower = question.lower()
        
        task_info = {
            "needs_data": False,
            "data_type": None,
            "operation": None,
        }
        
        # Command strings
        if "command" in question_lower:
            task_info["question_type"] = "command"
            if "uv http get" in question_lower:
                task_info["command_type"] = "uv_http"
            elif "git" in question_lower:
                task_info["command_type"] = "git"
        
        # Markdown links
        elif "markdown" in question_lower or (".md" in question_lower and "link" in question_lower):
            task_info["question_type"] = "markdown_link"
        
        # Audio transcription
        elif "audio" in question_lower or any(ext in question_lower for ext in [".opus", ".mp3", ".wav"]):
            task_info["needs_data"] = True
            task_info["data_type"] = "audio"
            audio_match = re.search(r'(/[\w\-/]+\.(?:opus|mp3|wav))', question)
            if audio_match:
                task_info["audio_path"] = audio_match.group(1)
        
        # Image processing
        elif ("heatmap" in question_lower or ".png" in question_lower) and "color" in question_lower:
            task_info["needs_data"] = True
            task_info["data_type"] = "image"
            img_match = re.search(r'(/[\w\-/]+\.(?:png|jpg|jpeg))', question)
            if img_match:
                task_info["image_path"] = img_match.group(1)
            if "frequent" in question_lower and "color" in question_lower:
                task_info["operation"] = "dominant_color"
        
        # CSV normalization
        elif "normalize" in question_lower and "csv" in question_lower:
            task_info["needs_data"] = True
            task_info["data_type"] = "csv"
            task_info["operation"] = "normalize"
            csv_match = re.search(r'(/[\w\-/]+\.csv)', question)
            if csv_match:
                task_info["csv_path"] = csv_match.group(1)
        
        # PDF invoice
        elif "invoice" in question_lower and "pdf" in question_lower:
            task_info["needs_data"] = True
            task_info["data_type"] = "pdf_invoice"
            pdf_match = re.search(r'(/[\w\-/]+\.pdf)', question)
            if pdf_match:
                task_info["pdf_path"] = pdf_match.group(1)
        
        # GitHub API
        elif "github api" in question_lower or "api.github.com" in question:
            task_info["needs_data"] = True
            task_info["data_type"] = "github_api"
            task_info["operation"] = "count"
        
        # Existing logic for other data types
        elif "download" in question_lower or "csv" in question_lower:
            task_info["needs_data"] = True
            task_info["data_type"] = "file"
        
        # Operations
        if "sum" in question_lower:
            task_info["operation"] = "sum"
        elif "count" in question_lower:
            task_info["operation"] = "count"
        elif "calculate" in question_lower:
            task_info["operation"] = "calculate"
        
        return task_info
    
    def _extract_command_answer(self, question: str, task_info: Dict[str, Any], quiz_data: Dict[str, Any]) -> Optional[str]:
        """Extract command string answers"""
        
        # UV HTTP GET command
        if task_info.get("command_type") == "uv_http":
            # Extract URL more robustly
            url_pattern = r'https?://[^\s<>"\']+\.json[^\s<>"\']*'
            url_match = re.search(url_pattern, question)
            if not url_match:
                # Try alternative patterns
                url_pattern = r'https?://[^\s<>"\']+/project2/uv\.json[^\s<>"\']*'
                url_match = re.search(url_pattern, question)
            
            if url_match:
                url = url_match.group(0)
                
                # Extract email parameter pattern
                if "email=" in url or "email = " in question.lower():
                    # Get email from config
                    email = Config.EMAIL
                    
                    # Replace email placeholder
                    if "<your email>" in question.lower():
                        # Find and replace the placeholder
                        question_lower = question.lower()
                        placeholder_start = question_lower.find("<your email>")
                        if placeholder_start != -1:
                            placeholder_end = placeholder_start + len("<your email>")
                            original_text = question[placeholder_start:placeholder_end]
                            url = url.replace(original_text, email)
                    
                    # Add email parameter if missing
                    if "email=" not in url:
                        # Check if URL already has query parameters
                        if '?' in url:
                            url += f'&email={email}'
                        else:
                            url += f'?email={email}'
                    else:
                        # Replace existing email parameter
                        url = re.sub(r'email=[^&]+', f'email={email}', url)
                
                # Build command
                command = f'uv http get "{url}"'
                
                # Check for headers
                if "accept" in question.lower() and "application/json" in question.lower():
                    command += ' -H "Accept: application/json"'
                
                # Add verbose flag if mentioned
                if "-v" in question or "--verbose" in question:
                    command += ' -v'
                
                print(f"📝 Extracted uv command: {command}")
                return command
        
        # Git commands
        elif task_info.get("command_type") == "git":
            # Extract filename and commit message
            file_match = re.search(r'stage only\s+([\w\-_.]+)', question, re.IGNORECASE)
            msg_match = re.search(r'message\s+["\']([^"\']+)["\']', question, re.IGNORECASE)
            
            if file_match and msg_match:
                filename = file_match.group(1)
                message = msg_match.group(1)
                
                # Return both commands as newline-separated
                commands = f'git add {filename}\ngit commit -m "{message}"'
                print(f"Extracted git commands: {commands}")
                return commands
            
            # Try alternative patterns
            if "git add" in question_lower and "git commit" in question_lower:
                # Extract the actual commands from the question
                add_match = re.search(r'git add\s+[\w\-_.]+', question, re.IGNORECASE)
                commit_match = re.search(r'git commit -m ["\'][^"\']+["\']', question, re.IGNORECASE)
                
                if add_match and commit_match:
                    commands = f'{add_match.group(0)}\n{commit_match.group(0)}'
                    print(f"Extracted git commands from text: {commands}")
                    return commands
        
        return None
    
    def _extract_markdown_link(self, question: str) -> Optional[str]:
        """Extract markdown link path"""
        # Look for the exact path mentioned
        path_match = re.search(r'(/project2/[\w\-/]+\.md)', question)
        if path_match:
            return path_match.group(1)
        
        # More general pattern
        path_match = re.search(r'(/[\w\-/]+\.md)', question)
        if path_match:
            return path_match.group(1)
        
        return None
    
    async def _process_image_color(self, task_info: Dict[str, Any], quiz_data: Dict[str, Any]) -> Optional[str]:
        """Extract dominant color from image"""
        try:
            from urllib.parse import urljoin
            base_url = quiz_data.get("url", "")
            image_path = task_info.get("image_path", "")
            
            if not image_path:
                return None
            
            image_url = urljoin(base_url, image_path)
            print(f"📥 Downloading image from: {image_url}")
            
            image_content = self.data_processor.download_file(image_url)
            img = Image.open(io.BytesIO(image_content))
            
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            pixels = list(img.getdata())
            color_counter = Counter(pixels)
            most_common_color = color_counter.most_common(1)[0][0]
            
            hex_color = '#{:02x}{:02x}{:02x}'.format(
                most_common_color[0],
                most_common_color[1],
                most_common_color[2]
            )
            
            print(f"🎨 Dominant color: {hex_color} (RGB: {most_common_color})")
            return hex_color
            
        except Exception as e:
            print(f"❌ Error processing image: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _process_csv_normalization(self, task_info: Dict[str, Any], quiz_data: Dict[str, Any]) -> Optional[List[Dict]]:
        """Normalize CSV to JSON format with proper ordering"""
        try:
            from urllib.parse import urljoin
            base_url = quiz_data.get("url", "")
            csv_path = task_info.get("csv_path", "")
            
            if not csv_path:
                return None
            
            csv_url = urljoin(base_url, csv_path)
            print(f"📥 Downloading CSV from: {csv_url}")
            
            csv_content = self.data_processor.download_file(csv_url)
            df = self.data_processor.parse_csv(csv_content)
            
            print(f"📊 CSV columns: {list(df.columns)}")
            print(f"📊 Sample data:\n{df.head()}")
            
            # Create a clean copy
            df_clean = df.copy()
            
            # Normalize column names to snake_case
            column_mapping = {}
            for col in df_clean.columns:
                original_col = str(col).strip()
                # Clean and normalize
                normalized = original_col.lower()
                normalized = re.sub(r'[^\w\s]', '', normalized)
                normalized = re.sub(r'\s+', '_', normalized)
                column_mapping[original_col] = normalized
            
            df_clean = df_clean.rename(columns=column_mapping)
            print(f"✅ Normalized columns: {list(df_clean.columns)}")
            
            # Ensure correct column order as per requirements
            required_columns = ['id', 'name', 'joined', 'value']
            
            # Rename columns to match exact requirements
            for col in df_clean.columns:
                col_lower = col.lower()
                if 'id' in col_lower:
                    df_clean = df_clean.rename(columns={col: 'id'})
                elif 'name' in col_lower:
                    df_clean = df_clean.rename(columns={col: 'name'})
                elif 'joined' in col_lower or 'date' in col_lower:
                    df_clean = df_clean.rename(columns={col: 'joined'})
                elif 'value' in col_lower:
                    df_clean = df_clean.rename(columns={col: 'value'})
            
            # Ensure all required columns exist
            for req_col in required_columns:
                if req_col not in df_clean.columns:
                    print(f"⚠️ Missing required column: {req_col}")
                    # Try to find similar column
                    for col in df_clean.columns:
                        if req_col in col.lower():
                            df_clean = df_clean.rename(columns={col: req_col})
                            break
            
            # Reorder columns
            existing_cols = [col for col in required_columns if col in df_clean.columns]
            df_clean = df_clean[existing_cols]
            
            # Convert data types
            if 'id' in df_clean.columns:
                df_clean['id'] = pd.to_numeric(df_clean['id'], errors='coerce').fillna(0).astype(int)
            
            if 'value' in df_clean.columns:
                df_clean['value'] = pd.to_numeric(df_clean['value'], errors='coerce').fillna(0).astype(int)
            
            if 'joined' in df_clean.columns:
                # Try multiple date formats
                for date_format in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%Y', '%m-%d-%Y']:
                    try:
                        df_clean['joined'] = pd.to_datetime(df_clean['joined'], format=date_format, errors='coerce')
                        # Check if any dates were successfully parsed
                        if df_clean['joined'].notna().any():
                            break
                    except:
                        continue
                
                # If all parsing failed, try inferring
                if df_clean['joined'].isna().all():
                    df_clean['joined'] = pd.to_datetime(df_clean['joined'], errors='coerce')
                
                # Format to ISO-8601
                df_clean['joined'] = df_clean['joined'].dt.strftime('%Y-%m-%d')
            
            # Sort by id if exists
            if 'id' in df_clean.columns:
                df_clean = df_clean.sort_values('id')
            
            result = df_clean.to_dict(orient='records')
            
            print(f"✅ Normalized {len(result)} records")
            if result:
                print(f"📋 Sample record: {result[0]}")
            
            return result
            
        except Exception as e:
            print(f"❌ Error normalizing CSV: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _process_pdf_invoice(self, task_info: Dict[str, Any], quiz_data: Dict[str, Any]) -> Optional[float]:
        """Extract and calculate invoice total from PDF"""
        try:
            from urllib.parse import urljoin
            base_url = quiz_data.get("url", "")
            pdf_path = task_info.get("pdf_path", "")
            
            if not pdf_path:
                return None
            
            pdf_url = urljoin(base_url, pdf_path)
            print(f"📥 Downloading PDF from: {pdf_url}")
            
            pdf_content = self.data_processor.download_file(pdf_url)
            pdf_data = self.data_processor.parse_pdf(pdf_content)
            
            text = pdf_data["text"]
            print(f"📄 PDF text preview: {text[:300]}")
            
            total = 0.0
            lines = text.split('\n')
            
            # Skip header lines and look for line items
            in_items = False
            for line in lines:
                line_lower = line.lower()
                
                # Detect start of line items
                if any(word in line_lower for word in ['quantity', 'item', 'description']):
                    in_items = True
                    continue
                
                # Detect end of line items
                if any(word in line_lower for word in ['subtotal', 'total', 'tax', 'amount due']):
                    break
                
                if in_items or not any(word in line_lower for word in ['invoice', 'bill', 'date', 'number']):
                    # Extract numbers from line
                    numbers = re.findall(r'\d+\.?\d*', line)
                    
                    if len(numbers) >= 2:
                        try:
                            quantity = float(numbers[0])
                            unit_price = float(numbers[1])
                            
                            # Sanity checks
                            if 0 < quantity <= 1000 and 0 < unit_price <= 10000:
                                line_total = quantity * unit_price
                                total += line_total
                                print(f"  Line: {quantity} × ${unit_price} = ${line_total}")
                        except:
                            pass
            
            total = round(total, 2)
            print(f"💰 Invoice total: ${total}")
            return total
            
        except Exception as e:
            print(f"❌ Error processing invoice: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _process_github_tree(self, task_info: Dict[str, Any], quiz_data: Dict[str, Any]) -> Optional[int]:
        """Process GitHub tree API question"""
        try:
            question = quiz_data.get("question", "")
            
            # Extract GitHub API URL from question
            api_pattern = r'https?://api\.github\.com/repos/[^\s<>"\']+'
            api_match = re.search(api_pattern, question)
            
            if not api_match:
                print("⚠️ No GitHub API URL found in question")
                return None
            
            api_url = api_match.group(0)
            print(f"🌐 Calling GitHub API: {api_url}")
            
            # Call GitHub API
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'QuizSolver/1.0'
            }
            
            response = requests.get(api_url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Extract prefix from question
            prefix = None
            prefix_match = re.search(r'prefix\s+["\']([^"\']+)["\']', question, re.IGNORECASE)
            if prefix_match:
                prefix = prefix_match.group(1)
                print(f"📁 Looking for files with prefix: {prefix}")
            
            # Count .md files under the given prefix
            md_count = 0
            if 'tree' in data:
                for item in data['tree']:
                    path = item.get('path', '')
                    if path.endswith('.md'):
                        if prefix:
                            if path.startswith(prefix):
                                md_count += 1
                                print(f"  ✓ Found: {path}")
                        else:
                            md_count += 1
                            print(f"  ✓ Found: {path}")
            
            print(f"📄 Found {md_count} .md files")
            
            # Get email from config and calculate offset
            email = Config.EMAIL
            email_length = len(email)
            offset = email_length % 2
            
            final_count = md_count + offset
            print(f"📧 Email: {email}")
            print(f"📧 Email length: {email_length}, offset: {offset}")
            print(f"🧮 Final count: {md_count} + {offset} = {final_count}")
            
            return final_count
            
        except Exception as e:
            print(f"❌ Error processing GitHub API: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _get_audio_url(self, task_info: Dict[str, Any], quiz_data: Dict[str, Any]) -> Optional[str]:
        """Get audio file URL for transcription"""
        try:
            from urllib.parse import urljoin
            base_url = quiz_data.get("url", "")
            audio_path = task_info.get("audio_path", "")
            
            if not audio_path:
                return None
            
            audio_url = urljoin(base_url, audio_path)
            print(f"🔊 Audio file URL: {audio_url}")
            return audio_url
        except Exception as e:
            print(f"❌ Error getting audio URL: {e}")
            return None
    
    async def _fetch_and_process_data(self, task_info: Dict[str, Any], quiz_data: Dict[str, Any]) -> Dict[str, Any]:
        """Existing data fetching logic (keep your original implementation)"""
        from urllib.parse import urljoin
        context = {}
        
        try:
            if task_info.get("data_type") == "scrape" and task_info.get("scrape_url"):
                # Your existing scraping logic
                pass
            elif task_info.get("data_type") == "file":
                # Your existing file processing logic
                pass
            elif task_info.get("data_type") == "api":
                # Your existing API logic
                pass
        except Exception as e:
            context["error"] = f"Data processing error: {str(e)}"
        
        return context
    
    def submit_answer(self, submit_url: str, email: str, secret: str, quiz_url: str, answer: Any) -> Dict[str, Any]:
        """Submit answer to quiz endpoint"""
        formatted_answer = self._format_answer(answer)
        
        payload = {
            "email": email,
            "secret": secret,
            "url": quiz_url,
            "answer": formatted_answer
        }
        
        payload_json = json.dumps(payload)
        payload_size = len(payload_json.encode('utf-8'))
        if payload_size > 1024 * 1024:
            return {
                "error": "Payload too large",
                "correct": False,
                "reason": f"Payload size {payload_size} bytes exceeds 1MB limit"
            }
        
        try:
            response = requests.post(submit_url, json=payload, timeout=30, headers={
                'Content-Type': 'application/json'
            })
            response.raise_for_status()
            result = response.json()
            
            if "correct" not in result:
                result["correct"] = False
            if "url" not in result:
                result["url"] = None
            if "reason" not in result:
                result["reason"] = None
                
            return result
        except Exception as e:
            return {
                "error": str(e),
                "correct": False,
                "reason": f"Request failed: {str(e)}"
            }
    def _clean_dict_for_json(self, data: Dict) -> Dict:
        """Clean dictionary for JSON serialization"""
        cleaned = {}
        for key, value in data.items():
            if pd.isna(value):
                cleaned[key] = None
            elif isinstance(value, dict):
                cleaned[key] = self._clean_dict_for_json(value)
            elif isinstance(value, list):
                cleaned[key] = self._clean_list_for_json(value)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        return cleaned
    
    def _clean_list_for_json(self, data: List) -> List:
        """Clean list for JSON serialization"""
        cleaned = []
        for item in data:
            if pd.isna(item):
                cleaned.append(None)
            elif isinstance(item, dict):
                cleaned.append(self._clean_dict_for_json(item))
            elif isinstance(item, list):
                cleaned.append(self._clean_list_for_json(item))
            elif isinstance(item, (str, int, float, bool)) or item is None:
                cleaned.append(item)
            else:
                cleaned.append(str(item))
        return cleaned
    
    def _format_answer(self, answer: Any) -> Any:
        """Format answer to appropriate type"""
        if answer is None:
            return None
        
        # Handle lists and dicts with NaN values
        if isinstance(answer, list):
            return self._clean_list_for_json(answer)
        elif isinstance(answer, dict):
            return self._clean_dict_for_json(answer)
        elif isinstance(answer, (str, int, float, bool)):
            return answer
        
        if hasattr(answer, 'to_dict'):
            try:
                return answer.to_dict()
            except:
                return str(answer)
        
        return str(answer)
    