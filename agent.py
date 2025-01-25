import logging
import os
import base64
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
from supabase import create_client, Client
from PIL import Image
import fitz

load_dotenv(dotenv_path=".env.local")

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

logger = logging.getLogger("voice-agent")
logging.basicConfig(level=logging.INFO)

from openai import OpenAI

client = OpenAI()

if not os.getenv('OPENAI_API_KEY'):
    raise ValueError("OpenAI API key not found. Please check your .env file.")

images_folder = 'output_images'

gpt_model = "gpt-4o-mini"

def encode_image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
    return encoded_string

def analyze_images_with_gpt(question, image_paths):
    try:
        message_content = {"type": "text", "text": question}
        for image_path in image_paths:
            base64_image = encode_image_to_base64(image_path)
            message_content = [
                {"type": "text", "text": question},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
        response = client.chat.completions.create(
            model=gpt_model,
            messages=[
                {
                    "role": "user",
                    "content": message_content
                }
            ],
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error during GPT-4 Vision analysis: {e}"

def get_all_image_paths(folder):
    supported_formats = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff')
    image_paths = [
        os.path.join(folder, file)
        for file in os.listdir(folder)
        if file.lower().endswith(supported_formats)
    ]
    return image_paths

class AssistantFnc(llm.FunctionContext):
    @llm.ai_callable(description="Answer user questions based on existing images.")
    async def answer_question(self, question: Annotated[str, llm.TypeInfo(description="The user's question about the images.")]):
        image_paths = get_all_image_paths(images_folder)
        answer = analyze_images_with_gpt(question, image_paths)
        return answer

fnc_ctx = AssistantFnc()

async def entrypoint(ctx: JobContext):
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=system_prompt,
    )

    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    participant = await ctx.wait_for_participant()
    logger.info(f"Starting voice assistant for participant {participant.identity}")

    assistant = VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=elevenlabs.TTS(
            model_id="eleven_turbo_v2",
            api_key=os.getenv("ELEVENLABS_API_KEY")
        ),
        chat_ctx=initial_ctx,
        fnc_ctx=fnc_ctx,
    )

    assistant.start(ctx.room, participant)

    await assistant.say("Hello! How can I assist you today?", allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=lambda proc: proc.userdata.update({"vad": silero.VAD.load()}),
        ),
    )
