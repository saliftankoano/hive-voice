import os
import asyncio
import logging
from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import openai, deepgram, silero, elevenlabs, turn_detector
from prompts.base import system_prompt
from typing import Annotated, List
import time
from pinecone import Pinecone
from openai import AsyncOpenAI

load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")
logging.basicConfig(level=logging.INFO)

gpt_model = "gpt-4o-mini"

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

class RAG(llm.FunctionContext):
    def __init__(self):
        super().__init__()
        self.openai_client = AsyncOpenAI()
        
        # Initialize Pinecone
        self.pc = Pinecone(
            api_key=os.getenv("PINECONE_API_KEY")
        )
        
        # Connect to index
        self.index_name = os.getenv("PINECONE_INDEX_NAME")
        self.index = self.pc.Index(self.index_name)

    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding for text using OpenAI's API."""
        try:
            response = await self.openai_client.embeddings.create(
                input=text,
                model="text-embedding-ada-002"
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Error getting embedding: {e}")
            return None
    
    @llm.ai_callable()
    async def run(self, query: Annotated[str, "The user's question"]):
        """Get context from documents to answer questions."""
        logger.info(f"Running RAG for query: {query}")
        
        start_time = time.time()
        
        try:
            # Get query embedding
            query_embedding = await self.get_embedding(query)
            if not query_embedding:
                return "I apologize, but I encountered an error while processing your question. Please try again."
            
            # Query Pinecone
            results = self.index.query(
                vector=query_embedding,
                top_k=3,
                include_metadata=True
            )
            
            if not results.matches:
                return "I apologize, but I don't have enough context to answer that question accurately. Could you please rephrase or ask about something else?"
            
            # Format contexts with relevance scores
            contexts = []
            for match in results.matches:
                contexts.append({
                    'text': match.metadata.get('text', ''),
                    'metadata': match.metadata,
                    'relevance': match.score
                })
            
            # Sort by relevance and combine
            contexts.sort(key=lambda x: x['relevance'], reverse=True)
            combined_context = "\n\n".join(
                f"Context (relevance: {c['relevance']:.2f}):\n{c['text']}" 
                for c in contexts
            )
            
            logger.debug(f"Query time: {time.time() - start_time:.2f}s")
            
            response = f"""
            Here are relevant contexts from the databse to help answer the question :
            {combined_context}
            """
            
            return response
            
        except Exception as e:
            logger.error(f"Error querying Pinecone: {e}")
            return "I apologize, but I encountered an error while searching for information. Please try again."

async def entrypoint(ctx: JobContext):
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=system_prompt,
    )

    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    try:
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=30)
        logger.info(f"Participant {participant.identity} joined")
    except asyncio.TimeoutError:
        logger.error("Timeout waiting for a participant to join.")
        return
    except Exception as e:
        logger.error(f"Error while waiting for participant: {e}")
        return

    RAGTool = RAG()

    assistant = VoiceAssistant(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=elevenlabs.TTS(
            model_id="eleven_turbo_v2",
            api_key=os.getenv("ELEVENLABS_API_KEY")
        ),
        chat_ctx=initial_ctx,
        turn_detector=turn_detector.EOUModel(),
        fnc_ctx=RAGTool,
    )

    assistant.start(ctx.room, participant)
    await assistant.say("Hello I'm Jenna! How can I assist you today?", allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )
