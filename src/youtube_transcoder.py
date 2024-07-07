import re
import traceback
from os.path import join, basename

from unidecode import unidecode

from pytube import YouTube
from moviepy.editor import VideoFileClip

from google.cloud import speech_v1p1beta1 as speech
from google.cloud import storage

import vertexai
from vertexai.generative_models import GenerativeModel

from env import output_path
from src.utils import delete_files_from_folder
from pytube.innertube import _default_clients

_default_clients["ANDROID_MUSIC"] = _default_clients["ANDROID_CREATOR"]


def transcoder(name, on_update):
    filename = re.sub(r'[^a-zA-Z0-9\s]', '', unidecode(name)).replace(" ", "_")

    video_output_path = join(output_path, f"{filename}.mp4")
    audio_output_path = join(output_path, f"{filename}.wav")

    resume = None

    try:
        # Load the video file
        video = VideoFileClip(video_output_path)

        # Extract the audio from the video and save as a WAV file
        video.audio.write_audiofile(
            filename=audio_output_path,
            codec='pcm_s16le',
            ffmpeg_params=[
                '-ar', '16000',
                '-ac', '1'
            ]
        )
    except Exception as e:
        on_update(f"Error while converting video to audio:\n{traceback.format_exc()}")

    try:
        # Upload local audio file to GCS
        bucket_name = "transcription-reunion"
        destination_blob_name = f"audio-files/{filename}.wav"
        on_update(f"Uploading to gs://{bucket_name}/{destination_blob_name}")

        gcs_uri = upload_to_gcs(bucket_name, audio_output_path, destination_blob_name)
    except Exception as e:
        on_update(f"Error while uploading audio to storage:\n{traceback.format_exc()}")

    try:
        on_update(f"Transcribing {gcs_uri}")
        # Transcribe the audio file
        transcription = transcribe_audio(gcs_uri)
    except Exception as e:
        on_update(f"Error while transcribing:\n{traceback.format_exc()}")

    try:
        on_update("Generating resume")
        # Generating a textual resume of the audio file
        resume_name = f"{filename}.md"
        with open(join(output_path, resume_name), "w+") as f:
            resume = generate_resume(name, transcription)
            f.write(resume)

        upload_to_gcs(bucket_name, join(output_path, resume_name), "transcripts/" + resume_name)

        delete_files_from_folder(output_path)
    except Exception as e:
        on_update(f"Error while generating resume:\n{traceback.format_exc()}")

    if not resume:
        return "Unkown error while generating resume."

    return resume


def youtube_transcoder(youtube_url, on_update):
    # Define the path where to save the video

    try:
        on_update(f"Downloading {youtube_url}...")
        # Create a YouTube object
        yt = YouTube(youtube_url)
        filename = re.sub(r'[^a-zA-Z0-9\s]', '', unidecode(yt.title)).replace(" ", "_")

        # Get the highest resolution stream available
        stream = yt.streams.get_highest_resolution()

        # Download the video
        stream.download(output_path=output_path, filename=filename + ".mp4")
    except Exception as e:
        on_update(f"Error while downloading youtube video:\n{traceback.format_exc()}")

    return transcoder(yt.title, on_update)


def video_transcoder(video, on_update):
    filename = re.sub(r'[^a-zA-Z0-9\s]', '', unidecode(video.filename)).replace(" ", "_")

    with open(join(output_path, f"{filename}.mp4"), "wb") as f:
        f.write(video.read())

    return transcoder(video.filename, on_update)


def transcribe_audio(gcs_uri):
    client = speech.SpeechClient()

    audio = speech.RecognitionAudio(uri=gcs_uri)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        language_code="fr-FR",
        sample_rate_hertz=16000,
        enable_automatic_punctuation=True,
        model="latest_long"
    )

    operation = client.long_running_recognize(config=config, audio=audio)
    response = operation.result(timeout=36000)

    text = ""
    for result in response.results:
        text += result.alternatives[0].transcript

    return text


def upload_to_gcs(bucket_name, source_file_path, destination_blob_name):
    """Uploads a file to the bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)

    blob.upload_from_filename(source_file_path)

    return f'gs://{bucket_name}/{destination_blob_name}'


def generate_resume(text_title, text_to_resume):
    vertexai.init(project="taskwidget-b17c3", location="europe-west3")

    model = GenerativeModel(model_name="gemini-1.5-flash-001")

    return model.generate_content(
        "Le texte fournit ci-dessous est une conversation entre une ou plusieurs personnes, au format markdown, "
        "fait d'abord un court résumé du texte, fait ensuite le sommaire du texte et "
        f"fait enfin un résumé long et détaillé, le titre du texte est {text_title}.\n{text_to_resume}"
    ).text
