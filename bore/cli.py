
# borecli/bore/cli.py

import asyncio
import signal
import threading
import traceback

import click
import requests

from bore.config import (
    DEFAULT_TOKEN_LIFETIME,
    get_email,
    get_token,
    is_authenticated,
    get_remaining_session_time,
)
from bore.parse_duration import parse_duration

from bore.auth import (
    login,
    logout,
 BoreAuthError,

)

from bore.tunnel.client import TunnelClient
API_URL = "https://api.borehook.com"

shutdown_requested = False
_stop_event = threading.Event()

# 
    
def request_shutdown(signum=None, frame=None):
    global shutdown_requested
    if shutdown_requested:
        return
    shutdown_requested = True
    click.echo("\n\n🛑 Disconnecting...")

    try:
        loop = asyncio.get_running_loop()
        current = asyncio.current_task(loop)
        for task in asyncio.all_tasks(loop):
            if task is not current:
                task.cancel()
    except RuntimeError:
        pass  # no loop running yet



@click.group()
def cli():
    pass


@cli.command(name="login")
@click.option("--email", prompt=True)
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
)
@click.option(
    "--time",
    default=None,
    help="Session duration (e.g. 30m, 2h, 1d). Defaults to 1h.",
)
def login_cmd(email, password, time):

    if is_authenticated():
        click.echo(
            f"Already logged in as {get_email()}"
        )
        return

    try:
        if time:
            lifetime = parse_duration(time)
        else:
            lifetime = DEFAULT_TOKEN_LIFETIME

        session = login(
            email=email,
            password=password,
            lifetime=lifetime,
        )

        click.echo("\n✅ Login successful")
        click.echo(f"Account: {session['email']}")

    except ValueError as exc:
        click.echo(
            f"\n❌ Invalid time: {exc}",
            err=True,
        )
        raise click.exceptions.Exit(1)


    except BoreAuthError as exc:
        click.echo(
            f"\n❌ {exc}",
            err=True,
        )
        raise click.exceptions.Exit(1)

    except Exception:
        # Never print the raw exception because it may contain
        # the API URL, internal paths, or other implementation details.
        click.echo(
            "\n❌ Unable to log in. Please try again later.",
            err=True,
        )
        raise click.exceptions.Exit(1)



    except BoreAuthError as exc:
        click.echo(
            f"\n❌ {exc}",
            err=True,
        )
        raise click.exceptions.Exit(1)

    except Exception:
        # Never print the raw exception because it may contain
        # the API URL, internal paths, or other implementation details.
        click.echo(
            "\n❌ Unable to log in. Please try again later.",
            err=True,
        )
        raise click.exceptions.Exit(1)


@cli.command()
def whoami():

    email = get_email()


    if not email:

        click.echo(
            "Not logged in."
        )

        return


    click.echo(
        f"Logged in as: {email}"
    )



@cli.command("logout")
def logout_command():

    """
    Log out of BoreHook.
    """

    logout()
   

    click.secho(
        "✅ Successfully logged out.",
        fg="green",
    )



@cli.command()
def connect():

    """
    Connect local application to BoreHook tunnel.
    """

    global shutdown_requested


    shutdown_requested = False

    _stop_event.clear()



    signal.signal(
        signal.SIGINT,
        request_shutdown,
    )


    try:

        signal.signal(
            signal.SIGTERM,
            request_shutdown,
        )

    except Exception:

        pass

    token = get_token()


    if not token:

        click.echo(
            "Not logged in. Run: bore login"
        )

        return
    
    remaining = get_remaining_session_time()

    if remaining <= 0:
        click.echo("Session expired. Please login again.")
        logout()
        return
    
    try:
        #
        # Get available tunnels
        #
        response = requests.get(
            f"{API_URL}/api/tunnels/",
            headers={
                "Authorization":
                f"Token {token}"
            },
            timeout=30,
        )
        response.raise_for_status()
        tunnels = response.json()

        if not tunnels:

            click.echo(
                "No tunnels found."
            )

            return
        click.echo(
            "\nAvailable Tunnels\n"
        )
        for index, tunnel in enumerate(
            tunnels,
            start=1,
        ):

            click.echo(
                f"[{index}] {tunnel['subdomain']}"
            )

        choice = click.prompt(
            "\nSelect tunnel",
            type=int,
        )
        if not (
            1 <= choice <= len(tunnels)
        ):

            click.echo(
                "Invalid selection."
            )

            return

        tunnel_id = tunnels[
            choice - 1
        ]["id"]



        #
        # Connect tunnel
        #

        response = requests.post(
            f"{API_URL}/api/tunnels/connect/",
            headers={
                "Authorization":
                f"Token {token}"
            },
            json={
                "tunnel_id": tunnel_id,
                "environment": "prod",
            },
            timeout=30,
        )

        
        response.raise_for_status()

        data = response.json()
        tunnel = data["tunnel"]

        local_port = tunnel.get(
            "local_port"
        )
        if not local_port:
            click.echo("Tunnel local_port is not configured.")
            return

        websocket_url = (
            f"{data['websocket_url']}"
            f"?token={token}"
        )

        click.echo(
            "\n🚀 Tunnel Connected"
        )

        click.echo(
            f"Tunnel ID: {tunnel['id']}"
        )

        click.echo(
            f"Subdomain: {tunnel['subdomain']}"
        )


        click.echo(
            f"Public URL: {data['public_url']}"
        )


        click.echo(f"Forwarding → http://127.0.0.1:{local_port}")

        click.echo("\nPress Ctrl+C to disconnect.")
        

        async def expire_session():
            await asyncio.sleep(remaining)
            click.echo("\n\n⏰ Session expired.")
            request_shutdown()
            

        async def run_client():
            client = TunnelClient(
                ws_url=websocket_url,
                local_port=local_port,
                tunnel_id=tunnel["id"],
            )

            client_task = asyncio.create_task(
                client.start(should_shutdown=lambda: shutdown_requested)
            )
            expire_task = asyncio.create_task(expire_session())

            try:
                done, pending = await asyncio.wait(
                    {client_task, expire_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError:
                pending = {client_task, expire_task}

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass  
 



        asyncio.run(
            run_client()
        )



    except requests.HTTPError as exc:

        click.echo(
            f"\n❌ HTTP Error: {exc}"
        )


    except KeyboardInterrupt:

        click.echo(
            "\n🛑 Stopped."
        )


    except Exception:
        traceback.print_exc()
        # click.echo(
        #     f"\n❌ {exc}"
        # )

    finally:

        click.echo(
            "\n🧹 Cleanup complete."
        )

        click.echo(
            "👋 Bore client stopped."
        )
        
if __name__ == "__main__":
    cli()
