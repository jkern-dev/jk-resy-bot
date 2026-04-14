import docker
import click
from flask import Flask, Response, stream_with_context, send_from_directory

app = Flask(__name__)

client = docker.from_env()


@app.route("/logs")
def logs():
    return Response(
        stream_with_context(generate_logs()), content_type="text/event-stream"
    )


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


def generate_logs():
    container = client.containers.get(docker_container_name)
    while True:
        for line in container.logs(stream=True, follow=True, tail=200):
            yield f"data: {line.decode('utf-8')}\n"


@app.route("/restart")
def restart_bot():
    container = client.containers.get(docker_container_name)
    container.restart()
    return "Restarted successfully"


@click.command
@click.option("--port", default=8991, show_default=True)
@click.option("--container-name", default="resy_bot", show_default=True)
@click.option(
    "--debug",
    is_flag=True,
    default=True,
    show_default=True,
)
def run_app(port: int, container_name: str, debug: bool):
    global docker_container_name
    docker_container_name = container_name
    app.run(debug=debug, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run_app()
