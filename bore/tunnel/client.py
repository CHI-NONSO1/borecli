# borecli/bore/tunnel/client.py

import asyncio
import logging

import websockets

from bore.frames import (receive_frame,send_frame,make_frame,)
from bore.protocol import MessageType
from bore.tunnel.dispatcher import ( MessageDispatcher,)
from bore.tunnel.heartbeat import (Heartbeat,)
logger = logging.getLogger(__name__)


class TunnelClient:
    """
    BoreHook async tunnel client.

    Handles:

    - websocket lifecycle
    - protocol receive loop
    - dispatcher
    - heartbeat
    - reconnect
    - graceful shutdown
    """

    def __init__(
        self,
        *,
        ws_url: str,
        local_port: int,
        tunnel_id: str,
        reconnect_delay: int = 5,
    ):

        self.ws_url = ws_url

        self.local_port = local_port

        self.tunnel_id = tunnel_id

        self.reconnect_delay = reconnect_delay


        self.websocket = None

        self.heartbeat = None

        self.dispatcher = None


        self._shutdown = False

        self._tasks = set()

    async def _safe_dispatch(self, frame):
                    try:
                        await self.dispatcher.dispatch(frame)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Dispatcher crashed")

    async def start(
        self,
        should_shutdown=lambda: False,
    ):

        """
        Start tunnel forever.
        """

        while not self._shutdown:


            if should_shutdown():

                break


            try:

                await self._connect()


                await self._receive_loop(
                    should_shutdown
                )


            except asyncio.CancelledError:

                break


            except Exception:

                logger.exception(
                    "Tunnel connection failed"
                )


            finally:

                await self._cleanup()



            if self._shutdown:

                break



            if should_shutdown():

                break



            logger.info(
                "Reconnecting in %s seconds",
                self.reconnect_delay,
            )


            # await asyncio.sleep(
            #     self.reconnect_delay
            # )
            for _ in range(self.reconnect_delay * 10):
                if should_shutdown():
                    return
                await asyncio.sleep(0.1)


    # async def stop(self):

    #     self._shutdown = True

    #     await self._cleanup()
        
    async def stop(self):
        self._shutdown = True

        if self.websocket:
            await self.websocket.close()

        await self._cleanup()



    async def _connect(self):

        logger.info(
            "Connecting %s",
            self.ws_url,
        )


        self.websocket = await websockets.connect(

            self.ws_url,

            ping_interval=None,

            max_size=None,

        )


        logger.info(
            "Tunnel websocket connected"
        )


        #
        # Create dispatcher
        #

        self.heartbeat = Heartbeat(
            self.websocket
        )


        self.dispatcher = MessageDispatcher(

            websocket=self.websocket,

            local_port=self.local_port,

            heartbeat=self.heartbeat,

        )
        await self.heartbeat.start()



    async def _receive_loop(
        self,
        should_shutdown,
    ):


        while True:


            if self._shutdown:

                break


            if should_shutdown():

                break


            try:
                frame = await asyncio.wait_for(
                    receive_frame(self.websocket),
                    timeout=1,
                )
            except asyncio.TimeoutError:
                continue
            # frame = await receive_frame(
            #     self.websocket
            # )


            if frame is None:

                break



            # task = asyncio.create_task(

            #     self.dispatcher.dispatch(
            #         frame
            #     )

            # )

            task = asyncio.create_task(
                self._safe_dispatch(frame)
            )
            
            self._tasks.add(task)


            task.add_done_callback(
                self._tasks.discard
            )



    async def _cleanup(self):


        #
        # cancel handlers
        #
        
        for task in list(self._tasks):
            task.cancel()

        if self._tasks:
            await asyncio.gather(
                *self._tasks,
                return_exceptions=True,
            )

        self._tasks.clear()
        


        #
        # stop heartbeat
        #

        if self.heartbeat:


            await self.heartbeat.stop()

            self.heartbeat = None



        #
        # close websocket
        #

        if self.websocket:


            try:

                await self.websocket.close()


            except Exception:

                pass


            self.websocket = None

        logger.info("Cancelling %d tasks", len(self._tasks))
        self.dispatcher = None