# Hive Agent

This is voice agent for Hive. It is built on top of Livekit and uses Pinecone for vector search.

How does it work?

1. The agent listens to the user's voice and transcribes it to text through Deepgram.
2. The agent uses the text to search for relevant information in the database using Pinecone.
3. The agent uses the relevant information to answer the user's question using the rag tool.
4. The agent uses the answer to generate a voice response using ElevenLabs.
5. The call is maintained through Livekit and Twilio.

## Setup

1. Clone the repository
2. Install the dependencies
3. Create a `.env.local` file with the following variables:
   - `LIVEKIT_URL`
   - `LIVEKIT_API_KEY`
   - `LIVEKIT_API_SECRET`
   - `ELEVENLABS_API_KEY`
   - `PINECONE_API_KEY`
   - `PINECONE_INDEX_NAME`
   - `LLAMA_API_KEY`
   - `OPENAI_API_KEY`
   - `DEEPGRAM_API_KEY`

## How to Parse PDF Documents from the data folder

1. `python3 mdrag.py`

## Run

1. `python3 agent.py dev`
