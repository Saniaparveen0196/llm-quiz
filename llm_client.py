import os
from typing import Optional, Dict, Any
import json
import re
from groq import Groq
import time
import random

class GroqClient:
    """Client for interacting with Groq Cloud API"""
    
    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key)
        self.request_timestamps = []
        
        self.available_models = [
            "llama-3.1-8b-instant",
            "llama-3.1-70b-versatile",
            "mixtral-8x7b-32768",
            "gemma2-9b-it"
        ]
        
        self.current_model = self.available_models[0]
        print(f"✓ Using Groq model: {self.current_model}")
    
    def _enforce_rate_limit(self):
        """Basic rate limiting"""
        now = time.time()
        self.request_timestamps = [ts for ts in self.request_timestamps if ts > now - 60]
        
        if len(self.request_timestamps) >= 25:
            sleep_time = 1.0
            print(f"⚠ Rate limit precaution: Waiting {sleep_time} seconds")
            time.sleep(sleep_time)
            
        self.request_timestamps.append(now)
    
    def solve_quiz(self, question: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Use Groq to solve a quiz question"""
        self._enforce_rate_limit()
        
        prompt = self._build_prompt(question, context)
        print(f"📤 Prompt length: {len(prompt)} characters")
        
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                print(f"📡 Calling Groq API (attempt {attempt + 1}/{max_retries})")
                
                if attempt > 0:
                    delay = base_delay ** attempt + random.uniform(0, 0.5)
                    print(f"⏱ Retry delay: {delay:.2f} seconds")
                    time.sleep(delay)
                
                response = self.client.chat.completions.create(
                    model=self.current_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant that solves quiz questions. Answer concisely and accurately. Provide only the answer without explanation unless specifically asked."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.1,
                    max_tokens=500
                )
                
                answer_text = response.choices[0].message.content
                print(f"✅ Groq API response received, length: {len(answer_text)}")
                print(f"📝 Response preview: {answer_text[:200]}...")
                
                answer = self._extract_answer(answer_text, question)
                print(f"🎯 Extracted answer: {answer} (type: {type(answer).__name__})")
                
                return {
                    "answer": answer,
                    "reasoning": answer_text,
                    "raw_response": answer_text
                }
                
            except Exception as e:
                error_str = str(e)
                print(f"❌ Groq API error: {error_str}")
                
                if "429" in error_str or "rate limit" in error_str.lower():
                    if attempt < max_retries - 1:
                        self._rotate_model()
                        continue
                    else:
                        return {
                            "answer": None,
                            "reasoning": "Rate limit exceeded after retries",
                            "raw_response": None
                        }
                else:
                    return {
                        "answer": None,
                        "reasoning": f"Groq API error: {error_str}",
                        "raw_response": None
                    }
        
        return {
            "answer": None,
            "reasoning": "Failed to get response from Groq API after retries",
            "raw_response": None
        }
    
    def _rotate_model(self):
        """Switch to a different model if current one has issues"""
        current_index = self.available_models.index(self.current_model)
        next_index = (current_index + 1) % len(self.available_models)
        self.current_model = self.available_models[next_index]
        print(f"🔄 Rotated to model: {self.current_model}")
    
    def _build_prompt(self, question: str, context: Optional[Dict[str, Any]]) -> str:
        """Build the prompt for the LLM"""
        prompt_parts = []
        
        prompt_parts.append("You are a quiz-solving assistant. Provide clear, concise answers.")
        
        if context:
            if "data" in context:
                data_str = str(context['data'])
                if len(data_str) > 3000:
                    data_str = data_str[:3000] + "... (truncated)"
                prompt_parts.append(f"\nData:\n{data_str}")
            if "dataframe" in context:
                df_str = str(context['dataframe'])
                if len(df_str) > 3000:
                    df_str = df_str[:3000] + "... (truncated)"
                prompt_parts.append(f"\nDataFrame:\n{df_str}")
            if "computed_result" in context:
                prompt_parts.append(f"\nComputed result: {context['computed_result']}")
            if "extracted_codes" in context:
                codes = context['extracted_codes']
                if codes:
                    prompt_parts.append(f"\nExtracted codes: {', '.join(codes[:3])}")
            if "files" in context:
                prompt_parts.append(f"Files available: {', '.join(context['files'])}")
            if "instructions" in context:
                instructions_str = str(context['instructions'])
                if len(instructions_str) > 2000:
                    instructions_str = instructions_str[:2000] + "... (truncated)"
                prompt_parts.append(f"Instructions: {instructions_str}")
            # Don't include scraped_html - it's too large
        
        prompt_parts.append(f"\nQuestion: {question}")
        prompt_parts.append("\nProvide a clear, concise answer. If the answer is a number, provide just the number. If it's text, provide the text. If it's a boolean, provide true or false. If it's a file, provide the base64 data URI.")
        prompt_parts.append("\nAnswer:")
        
        #return "\n".join(prompt_parts)
        
        
        # Add specific instructions based on question
        question_lower = question.lower()
        
        if "command" in question_lower:
            if "uv http get" in question_lower:
                prompt_parts.append("\nProvide the COMPLETE command string exactly as it should be run, including the full URL with email and all headers.")
            elif "git" in question_lower:
                prompt_parts.append("\nProvide BOTH git commands separated by a newline character.")
        elif "markdown" in question_lower and "link" in question_lower:
            prompt_parts.append("\nProvide only the exact file path.")
        elif any(word in question_lower for word in ["sum", "total", "count", "calculate"]):
            prompt_parts.append("\nProvide only the numeric answer (no explanation).")
        elif "transcribe" in question_lower:
            prompt_parts.append("\nProvide the exact transcription of the spoken phrase including any digits.")
        elif "color" in question_lower and "hex" in question_lower:
            prompt_parts.append("\nProvide the color in hex format: #rrggbb")
        elif "normalize" in question_lower and "json" in question_lower:
            prompt_parts.append("\nProvide a JSON array of objects with normalized data.")
        elif "audio" in question_lower or ".opus" in question_lower:
            prompt_parts.append("\nThe audio file contains a spoken passphrase followed by a 3-digit code. Transcribe the exact phrase including the digits.")    
        else:
            prompt_parts.append("\nProvide a clear, direct answer.")
        
        prompt_parts.append("\nAnswer:")
        
        return "\n".join(prompt_parts)
    
    def _extract_answer(self, response_text: str, question: str) -> Any:
        """Extract the answer from LLM response"""
        response_text = response_text.strip()
        question_lower = question.lower()
        
        # For command questions, extract the full command
        if "command" in question_lower:
            if "uv http get" in question_lower:
                # Extract full uv command
                uv_match = re.search(r'uv http get[^\n]+', response_text)
                if uv_match:
                    return uv_match.group(0).strip()
            elif "git" in question_lower:
                # Extract both git commands
                git_commands = re.findall(r'git (?:add|commit)[^\n]+', response_text)
                if len(git_commands) >= 2:
                    return '\n'.join(git_commands[:2])
        
        # For markdown links
        if "markdown" in question_lower or (".md" in question_lower and "link" in question_lower):
            path_match = re.search(r'/[\w\-/]+\.md', response_text)
            if path_match:
                return path_match.group(0)
        
        # For hex colors
        if "color" in question_lower and "hex" in question_lower:
            hex_match = re.search(r'#[0-9a-fA-F]{6}', response_text)
            if hex_match:
                return hex_match.group(0).lower()
        
        # For JSON arrays (CSV normalization)
        if "normalize" in question_lower or ("json" in question_lower and "array" in question_lower):
            # Try to find JSON array
            json_match = re.search(r'\[[\s\S]*\]', response_text)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except:
                    pass
        
        # Try to find JSON in response
        json_patterns = [
            r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*"answer"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',
            r'\{.*?"answer".*?\}',
        ]
        for pattern in json_patterns:
            json_match = re.search(pattern, response_text, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                    answer = parsed.get("answer")
                    if answer is not None:
                        return answer
                except:
                    pass
        
        # Try to find numbers
        number_patterns = [
            r'-?\d+\.\d+',
            r'-?\d+',
        ]
        for pattern in number_patterns:
            number_match = re.search(pattern, response_text)
            if number_match:
                numeric_keywords = ["sum", "count", "number", "total", "calculate", "value", "amount", "quantity"]
                if any(word in question_lower for word in numeric_keywords):
                    try:
                        num_str = number_match.group()
                        return float(num_str) if '.' in num_str else int(num_str)
                    except:
                        pass
        
        # Try to find boolean
        response_lower = response_text.lower()
        true_pos = response_lower.find("true")
        false_pos = response_lower.find("false")
        yes_pos = response_lower.find("yes")
        no_pos = response_lower.find("no")
        
        if true_pos != -1 or yes_pos != -1:
            if false_pos == -1 or (true_pos != -1 and (false_pos == -1 or true_pos < false_pos)):
                if no_pos == -1 or (yes_pos != -1 and (no_pos == -1 or yes_pos < no_pos)):
                    return True
        
        if false_pos != -1 or no_pos != -1:
            if true_pos == -1 or (false_pos != -1 and (true_pos == -1 or false_pos < true_pos)):
                if yes_pos == -1 or (no_pos != -1 and (yes_pos == -1 or no_pos < yes_pos)):
                    return False
        
        # Try to find base64 data URI
        base64_match = re.search(r'data:[^;]+;base64,([A-Za-z0-9+/=]+)', response_text)
        if base64_match:
            return base64_match.group(0)
        
        # Try to find quoted string
        string_match = re.search(r'["\']([^"\']+)["\']', response_text)
        if string_match:
            return string_match.group(1)
        
        # For URLs
        url_match = re.search(r'https?://[^\s<>"\']+', response_text)
        if url_match:
            return url_match.group(0)
        
        # For file paths
        if "/project2/" in response_text:
            path_match = re.search(r'/project2/[^\s<>"\']+', response_text)
            if path_match:
                return path_match.group(0)
        
        # Return cleaned text (first line)
        if '\n' in response_text:
            first_line = response_text.split('\n')[0].strip()
            if len(first_line) > 0:
                return first_line
        
        return response_text if response_text else None
# # groq_client.py
# import os
# from typing import Optional, Dict, Any
# import json
# import re
# from groq import Groq
# import time
# import random

# class GroqClient:
#     """Client for interacting with Groq Cloud API"""
    
#     def __init__(self, api_key: str):
#         self.client = Groq(api_key=api_key)
#         self.request_timestamps = []  # For rate limiting
        
#         # Available Groq models (all free tier)
#         self.available_models = [
#             "llama-3.1-8b-instant",      # Fastest, good for simple tasks
#             "llama-3.1-70b-versatile",   # More capable, slightly slower
#             "mixtral-8x7b-32768",        # Good balance
#             "gemma2-9b-it"               # Google's model on Groq
#         ]
        
#         # Start with the fastest model
#         self.current_model = self.available_models[0]
#         print(f"✓ Using Groq model: {self.current_model}")
    
#     def _enforce_rate_limit(self):
#         """Basic rate limiting - Groq is generous but still good practice"""
#         now = time.time()
#         # Keep only timestamps from last minute
#         self.request_timestamps = [ts for ts in self.request_timestamps if ts > now - 60]
        
#         # If more than 25 requests in last minute, wait a bit
#         if len(self.request_timestamps) >= 25:
#             sleep_time = 1.0
#             print(f"⚠ Rate limit precaution: Waiting {sleep_time} seconds")
#             time.sleep(sleep_time)
            
#         self.request_timestamps.append(now)
    
#     def solve_quiz(self, question: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
#         """
#         Use Groq to solve a quiz question
#         """
#         self._enforce_rate_limit()
        
#         prompt = self._build_prompt(question, context)
#         print(f"📤 Prompt length: {len(prompt)} characters")
        
#         max_retries = 3
#         base_delay = 1
        
#         for attempt in range(max_retries):
#             try:
#                 print(f"📡 Calling Groq API (attempt {attempt + 1}/{max_retries})")
                
#                 # Add small random delay between retries
#                 if attempt > 0:
#                     delay = base_delay ** attempt + random.uniform(0, 0.5)
#                     print(f"⏱ Retry delay: {delay:.2f} seconds")
#                     time.sleep(delay)
                
#                 response = self.client.chat.completions.create(
#                     model=self.current_model,
#                     messages=[
#                         {
#                             "role": "system",
#                             "content": "You are a helpful assistant that solves quiz questions. Answer concisely and accurately."
#                         },
#                         {
#                             "role": "user",
#                             "content": prompt
#                         }
#                     ],
#                     temperature=0.1,  # Low temperature for consistent answers
#                     max_tokens=500
#                 )
                
#                 answer_text = response.choices[0].message.content
#                 print(f"✅ Groq API response received, length: {len(answer_text)}")
#                 print(f"📝 Response preview: {answer_text[:200]}...")
                
#                 # Extract answer
#                 answer = self._extract_answer(answer_text, question)
#                 print(f"🎯 Extracted answer: {answer} (type: {type(answer).__name__})")
                
#                 return {
#                     "answer": answer,
#                     "reasoning": answer_text,
#                     "raw_response": answer_text
#                 }
                
#             except Exception as e:
#                 error_str = str(e)
#                 print(f"❌ Groq API error: {error_str}")
                
#                 # Handle rate limits
#                 if "429" in error_str or "rate limit" in error_str.lower():
#                     if attempt < max_retries - 1:
#                         # Try switching to a different model
#                         self._rotate_model()
#                         continue
#                     else:
#                         return {
#                             "answer": None,
#                             "reasoning": "Rate limit exceeded after retries",
#                             "raw_response": None
#                         }
#                 else:
#                     # Other errors
#                     return {
#                         "answer": None,
#                         "reasoning": f"Groq API error: {error_str}",
#                         "raw_response": None
#                     }
        
#         return {
#             "answer": None,
#             "reasoning": "Failed to get response from Groq API after retries",
#             "raw_response": None
#         }
    
#     def _rotate_model(self):
#         """Switch to a different model if current one has issues"""
#         current_index = self.available_models.index(self.current_model)
#         next_index = (current_index + 1) % len(self.available_models)
#         self.current_model = self.available_models[next_index]
#         print(f"🔄 Rotated to model: {self.current_model}")
    
#     def _build_prompt(self, question: str, context: Optional[Dict[str, Any]]) -> str:
#         """Build the prompt for the LLM"""
#         prompt_parts = []
        
#         prompt_parts.append("You are a helpful assistant that solves quiz questions. Answer concisely and accurately. Provide only the answer without explanation.")
        
#         if context:
#             if "data" in context:
#                 data_str = str(context['data'])
#                 if len(data_str) > 3000:
#                     data_str = data_str[:3000] + "... (truncated)"
#                 prompt_parts.append(f"\nData:\n{data_str}")
#             if "dataframe" in context:
#                 df_str = str(context['dataframe'])
#                 if len(df_str) > 3000:
#                     df_str = df_str[:3000] + "... (truncated)"
#                 prompt_parts.append(f"\nDataFrame:\n{df_str}")
#             if "computed_result" in context:
#                 prompt_parts.append(f"\nComputed result: {context['computed_result']}")
#             if "extracted_codes" in context:
#                 codes = context['extracted_codes']
#                 if codes:
#                     prompt_parts.append(f"\nExtracted codes from scraped page: {', '.join(codes[:3])}")
#             if "instructions" in context:
#                 instructions_str = str(context['instructions'])
#                 if len(instructions_str) > 2000:
#                     instructions_str = instructions_str[:2000] + "... (truncated)"
#                 prompt_parts.append(f"\nInstructions: {instructions_str}")
        
#         prompt_parts.append(f"\nQuestion: {question}")
        
#         # Add specific instructions based on question content
#         question_lower = question.lower()
#         if any(word in question_lower for word in ["sum", "total", "count", "calculate"]):
#             prompt_parts.append("\nProvide only the numeric answer.")
#         elif "uv http get" in question_lower or "command" in question_lower:
#             prompt_parts.append("\nProvide the exact command to run.")
#         elif "url" in question_lower or "link" in question_lower:
#             prompt_parts.append("\nProvide the exact URL or link.")
#         else:
#             prompt_parts.append("\nProvide a clear, concise answer. If the answer is a number, provide just the number. If it's text, provide the text. If it's a boolean, provide true or false. If it's a file, provide the base64 data URI.")
        
#         prompt_parts.append("\nAnswer:")
        
#         return "\n".join(prompt_parts)
    
#     def _extract_answer(self, response_text: str, question: str) -> Any:
#         """Extract the answer from LLM response"""
#         # Clean the response first
#         response_text = response_text.strip()
        
#         # Try to find JSON in response
#         json_patterns = [
#             r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*"answer"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',
#             r'\{.*?"answer".*?\}',
#         ]
#         for pattern in json_patterns:
#             json_match = re.search(pattern, response_text, re.DOTALL)
#             if json_match:
#                 try:
#                     parsed = json.loads(json_match.group())
#                     answer = parsed.get("answer")
#                     if answer is not None:
#                         return answer
#                 except:
#                     pass
        
#         # Try to find number (integer or float)
#         number_patterns = [
#             r'-?\d+\.\d+',  # Float
#             r'-?\d+',       # Integer
#         ]
#         for pattern in number_patterns:
#             number_match = re.search(pattern, response_text)
#             if number_match:
#                 numeric_keywords = ["sum", "count", "number", "total", "calculate", "value", "amount", "quantity"]
#                 if any(word in question.lower() for word in numeric_keywords):
#                     try:
#                         num_str = number_match.group()
#                         return float(num_str) if '.' in num_str else int(num_str)
#                     except:
#                         pass
        
#         # Try to find boolean
#         response_lower = response_text.lower()
#         true_pos = response_lower.find("true")
#         false_pos = response_lower.find("false")
#         yes_pos = response_lower.find("yes")
#         no_pos = response_lower.find("no")
        
#         if true_pos != -1 or yes_pos != -1:
#             if false_pos == -1 or (true_pos != -1 and (false_pos == -1 or true_pos < false_pos)):
#                 if no_pos == -1 or (yes_pos != -1 and (no_pos == -1 or yes_pos < no_pos)):
#                     return True
        
#         if false_pos != -1 or no_pos != -1:
#             if true_pos == -1 or (false_pos != -1 and (true_pos == -1 or false_pos < true_pos)):
#                 if yes_pos == -1 or (no_pos != -1 and (yes_pos == -1 or no_pos < yes_pos)):
#                     return False
        
#         # Try to find base64 data URI
#         base64_match = re.search(r'data:[^;]+;base64,([A-Za-z0-9+/=]+)', response_text)
#         if base64_match:
#             return base64_match.group(0)
        
#         # Try to find quoted string
#         string_match = re.search(r'["\']([^"\']+)["\']', response_text)
#         if string_match:
#             return string_match.group(1)
        
#         # Check for specific patterns
#         if "uv http get" in response_text:
#             # Extract the full uv command
#             lines = response_text.split('\n')
#             for line in lines:
#                 if line.strip().startswith('uv http get'):
#                     return line.strip()
        
#         # For URLs, extract the URL
#         url_match = re.search(r'https?://[^\s<>"\']+', response_text)
#         if url_match:
#             return url_match.group(0)
        
#         # For file paths
#         if "/project2/" in response_text:
#             path_match = re.search(r'/project2/[^\s<>"\']+', response_text)
#             if path_match:
#                 return path_match.group(0)
        
#         # Return cleaned text (first line)
#         if '\n' in response_text:
#             first_line = response_text.split('\n')[0].strip()
#             if len(first_line) > 0:
#                 return first_line
        
#         return response_text if response_text else None