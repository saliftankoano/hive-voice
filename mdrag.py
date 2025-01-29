import os
from typing import List, Dict, Any
from pinecone import Pinecone, ServerlessSpec
from openai import AsyncOpenAI
import logging
from dotenv import load_dotenv
import time
from tqdm import tqdm
from llama_parse import LlamaParse
import nest_asyncio
import json

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path=".env.local")

class DocumentProcessor:
    def __init__(self):
        self.openai_client = AsyncOpenAI()
        
        # Initialize Pinecone
        self.pc = Pinecone(
            api_key=os.getenv("PINECONE_API_KEY")
        )
        
        # Connect to index
        self.index_name = os.getenv("PINECONE_INDEX_NAME")
        if self.index_name not in self.pc.list_indexes().names():
            self.pc.create_index(
                name=self.index_name,
                dimension=1536,
                metric='cosine',
                spec=ServerlessSpec(
                    cloud=os.getenv("PINECONE_CLOUD", "aws"),
                    region=os.getenv("PINECONE_REGION", "us-east-1")
                )
            )
        self.index = self.pc.Index(self.index_name)
        
        # Initialize LlamaParse
        self.parser = LlamaParse(
            api_key=os.getenv("LLAMA_CLOUD_API_KEY"),
            auto_mode=True,
            auto_mode_trigger_on_image_in_page=True,
            auto_mode_trigger_on_table_in_page=True,
            result_type="markdown",
            complemental_formatting_instruction="",
            content_guideline_instruction=""
        )

    async def parse_document(self, file_path: str) -> dict:
        """Parse document and return structured content."""
        try:
            logger.info(f"Parsing document: {file_path}")
            result = await self.parser.aload_data(file_path)
            
            if result:
                # Save parsed content to a JSON file for inspection
                parsed_file = f"{file_path}_parsed.json"
                with open(parsed_file, 'w') as f:
                    json.dump({'text': result[0].text, 'metadata': result[0].metadata}, f, indent=2)
                logger.info(f"Saved parsed content to {parsed_file}")
                
                return {
                    'text': result[0].text,
                    'metadata': result[0].metadata
                }
            return None
        except Exception as e:
            logger.error(f"Error parsing document {file_path}: {e}")
            return None

    def chunk_text(self, text: str, metadata: dict = None, max_chunk_size: int = 1000) -> List[dict]:
        """Split text into chunks with overlap and preserve metadata and table integrity."""
        chunks = []
        overlap = 100
        
        if len(text) <= max_chunk_size:
            return [{'text': text, 'metadata': metadata}]
        
        start = 0
        while start < len(text):
            end = start + max_chunk_size
            
            if end >= len(text):
                chunk_text = text[start:]
            else:
                next_period = text.find('.', end - 50, end + 50)
                next_newline = text.find('\n', end - 50, end + 50)
                
                # Check if we're in the middle of a table
                last_table_start = text.rfind('\n|', start, end)
                if last_table_start != -1:
                    # Find the end of the table
                    current_pos = end
                    while current_pos < len(text):
                        next_line_start = text.find('\n', current_pos)
                        if next_line_start == -1:
                            break
                        next_line = text[next_line_start + 1:next_line_start + 2]
                        if next_line != '|':  # If next line doesn't start with |, we've found the table end
                            end = next_line_start
                            break
                        current_pos = next_line_start + 1
                
                # If no table is being processed, use regular breaking logic
                elif next_period != -1 and (next_newline == -1 or next_period < next_newline):
                    end = next_period + 1
                elif next_newline != -1:
                    end = next_newline + 1
                
                chunk_text = text[start:end]
            
            chunks.append({
                'text': chunk_text,
                'metadata': metadata
            })
            start = end - overlap
            
        return chunks

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for a list of texts using OpenAI's API."""
        try:
            response = await self.openai_client.embeddings.create(
                input=texts,
                model="text-embedding-ada-002"
            )
            return [data.embedding for data in response.data]
        except Exception as e:
            logger.error(f"Error getting embeddings: {e}")
            return []

    async def process_and_upload_document(self, file_path: str):
        """Process a document and upload its embeddings to Pinecone."""
        # Parse document
        parsed_doc = await self.parse_document(file_path)
        if not parsed_doc:
            logger.error(f"Failed to parse document: {file_path}")
            return
        
        # Create chunks with metadata
        chunks = self.chunk_text(
            parsed_doc['text'], 
            metadata={
                'source': os.path.basename(file_path),
                **parsed_doc.get('metadata', {})
            }
        )
        logger.info(f"Created {len(chunks)} chunks from document")
        
        # Process chunks in batches
        batch_size = 50
        for i in tqdm(range(0, len(chunks), batch_size), desc="Processing batches"):
            batch_chunks = chunks[i:i + batch_size]
            
            # Get embeddings for the batch
            texts = [chunk['text'] for chunk in batch_chunks]
            embeddings = await self.get_embeddings(texts)
            
            if not embeddings:
                continue
            
            # Prepare vectors for upload
            vectors = []
            for j, (chunk, embedding) in enumerate(zip(batch_chunks, embeddings)):
                vectors.append({
                    'id': f"{os.path.basename(file_path)}_{i+j}",
                    'values': embedding,
                    'metadata': {
                        'text': chunk['text'],
                        **chunk['metadata']
                    }
                })
            
            # Upload to Pinecone
            try:
                self.index.upsert(vectors=vectors)
                logger.info(f"Uploaded batch {i//batch_size + 1} to Pinecone")
            except Exception as e:
                logger.error(f"Error uploading to Pinecone: {e}")
            
            # Rate limiting
            time.sleep(0.5)

async def main():
    processor = DocumentProcessor()
    data_folder = "data"
    
    # Process all documents in the data folder
    supported_extensions = {'.pdf', '.md'}
    for filename in os.listdir(data_folder):
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext in supported_extensions:
            file_path = os.path.join(data_folder, filename)
            await processor.process_and_upload_document(file_path)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
    