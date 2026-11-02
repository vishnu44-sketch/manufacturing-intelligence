"""python manage.py run_mcp [--host 127.0.0.1] [--port 8090]

Starts Ask NOP as an MCP server (Streamable HTTP) at http://<host>:<port>/mcp for another chatbot.
Every request needs the header 'Authorization: Bearer <MCP_ACCESS_KEY from .env>'.
On the production server use --host 0.0.0.0 behind the company's HTTPS proxy.
"""
import uvicorn
from django.core.management.base import BaseCommand, CommandError

from portal.mcp_server import auth_is_off, build_app, our_llm_is_on


class Command(BaseCommand):
    help = "Run Ask NOP as an MCP server (Streamable HTTP at /mcp, needs MCP_ACCESS_KEY in .env)"

    def add_arguments(self, parser):
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8090)

    def handle(self, *args, **options):
        host, port = options["host"], options["port"]
        try:
            app = build_app(host=host)
        except ValueError as exc:  # no access key in .env
            raise CommandError(str(exc)) from None
        access = "NO access key (MCP_AUTH=off): anyone with the link can ask" if auth_is_off() else "Bearer key: MCP_ACCESS_KEY"
        llm = ("ask_nop with Ask NOP's own Groq (MCP_USE_OUR_LLM=on)" if our_llm_is_on()
               else "the caller's LLM writes the SQL and the answer - no Groq tokens used")
        self.stdout.write(self.style.SUCCESS(f"Ask NOP MCP server: http://{host}:{port}/mcp ({access}; {llm})"))
        uvicorn.run(app, host=host, port=port, log_level="info")
