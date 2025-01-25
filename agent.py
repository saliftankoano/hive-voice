import logging
import os
from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import openai, deepgram, silero, elevenlabs
from prompts.base import system_prompt
from livekit.plugins.elevenlabs.tts import Voice, VoiceSettings
from typing import Annotated, Dict
import os
from supabase import create_client, Client

load_dotenv(dotenv_path=".env.local")
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

logger = logging.getLogger("voice-agent")

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

class AssistantFnc(llm.FunctionContext):
    # the llm.ai_callable decorator marks this function as a tool available to the LLM
    # by default, it'll use the docstring as the function's description

    
    @llm.ai_callable( description="Process a payment")
    async def process_payment(
        self,
        # by using the Annotated type, arg description and type are available to the LLM
        card_number: Annotated[
            int, llm.TypeInfo(description="The card number to process the payment for")
        ],
        card_expiry: Annotated[
            str, llm.TypeInfo(description="The expiry date of the card")
        ],
        card_cvv: Annotated[
            int, llm.TypeInfo(description="The CVV of the card")
        ],
        card_name: Annotated[
            str, llm.TypeInfo(description="The name on the card")
        ],
    ):
        
        return "Payment processed successfully"
    
    @llm.ai_callable()
    async def get_order_details(self):
        return "Order details"

fnc_ctx = AssistantFnc()

async def entrypoint(ctx: JobContext):
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=system_prompt,
    )

    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    # This project is configured to use Deepgram STT, OpenAI LLM and TTS plugins
    # Other great providers exist like Cartesia and ElevenLabs
    # Learn more and pick the best one for your app:
    # https://docs.livekit.io/agents/plugins
    assistant = VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=elevenlabs.TTS(model_id="eleven_turbo_v2",api_key=os.getenv("ELEVENLABS_API_KEY")),
        chat_ctx=initial_ctx,
        fnc_ctx=fnc_ctx,
    )

    assistant.start(ctx.room, participant)

    # The agent should be polite and greet the user when it joins :)
    await assistant.say("Hi I'm Amy from Slice-sync, happy to help you with your order!", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )
