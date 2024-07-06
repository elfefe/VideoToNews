from os.path import abspath

import markdown
from flask import Flask, send_file, send_from_directory, request

from src.youtube_transcoder import youtube_transcoder, video_transcoder

app = Flask(__name__)

template_dir = abspath('resources/templates')


@app.route('/')
def default():
    # Use send_file to send the HTML file back as a response
    return send_from_directory(template_dir, "index.html")


@app.route("/transcribe", methods=['POST', 'GET'])
def transcribe():
    url = request.args.get('url')
    if url:
        transcription = youtube_transcoder(url, lambda x: print(x))
        return markdown.markdown(transcription)
    if request.method == 'POST':
        video = request.form['video']
        if video:
            transcription = video_transcoder(video, lambda x: print(x))
            return markdown.markdown(transcription)
    return "No video found"


if __name__ == '__main__':
    app.run(debug=True, port=7208)
