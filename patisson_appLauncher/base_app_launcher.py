"""This module contains the base class for launching applications."""

import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, TypeVar

import httpx

from patisson_appLauncher.printX import Block, BlockType, CallableWrapper, block_decorator

SocketPort = TypeVar("SocketPort")


@dataclass(kw_only=True)
class BaseAppLauncher(ABC):
    """
    Abstract base class for launching applications.

    Attributes:
        service_name (str): Name of the service being launched.
        host (str): Host address for the service.
        app_port (Optional[str | int]): Optional port for the application.

    Methods:
        get_socket(port): Creates and binds a socket to the given port, returning the socket and the
            bound port.
        socket_close(socket, port): Closes the socket and returns the original port.
        __post_init__(): Initializes the socket and logs the service setup.
        consul_register(check_path, check_interval, check_timeout, consul_register_address):
            Registers the service in Consul, setting up health check paths and intervals.
        app_run(): Abstract method to run the application (must be implemented in subclasses).
    """

    service_name: str
    host: str
    app_port: Optional[str | int] = None

    @staticmethod
    def get_socket(port: Optional[str | int]) -> tuple[socket.socket, int]:
        """
        Create a socket and binds it to the provided port.

        If a port is provided, it binds to that port; if no port is provided, it binds to a random
            available port.

        Args:
            port (Optional[str | int]): The port to bind the socket to. If not provided, a random port
                is used.

        Returns:
            tuple[socket.socket, int]: A tuple containing the created socket and the bound port number.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("", int(port) if port else 0))
        return sock, sock.getsockname()[1]

    @staticmethod
    def socket_close(socket: socket.socket, port: SocketPort) -> SocketPort:
        """
        Close the provided socket and returns the original port.

        Args:
            socket (socket.socket): The socket to be closed.
            port (SocketPort): The port associated with the socket.

        Returns:
            SocketPort: The original port number.
        """
        socket.close()
        return port

    def __post_init__(self) -> None:
        """
        Initialize the socket and port, and logs the service setup process.

        This method is automatically called after the object is initialized. It binds the socket
        to the specified port and logs the service startup information.
        """
        self.socket_, self.port = self.get_socket(self.app_port)
        Block(
            text=["App Launcher: Start setting up", f"{self.host}:{self.port}/{self.service_name}"],
            block_type=BlockType.HEAD,
        )()

    def consul_register(
        self,
        check_path: Optional[str] = None,
        check_interval: str = "30s",
        check_timeout: str = "3s",
        consul_register_address: str = "http://localhost:8500/v1/agent/service/register",
    ) -> None:
        """
        Register the service in Consul with health check configurations.

        This method registers the service with Consul, setting up the health check path,
        check interval, and check timeout. It sends the registration request to the Consul agent
        and verifies the registration was successful.

        Args:
            check_path (Optional[str]): The health check path for the service. Defaults to None.
            check_interval (str): The interval between health checks. Defaults to '30s'.
            check_timeout (str): The timeout for each health check. Defaults to '3s'.
            consul_register_address (str): The URL of the Consul agent to register the service. Defaults
                to 'http://localhost:8500/v1/agent/service/register'.

        Raises:
            AttributeError: If health_path is not defined before calling this method.
            ConnectionError: If the registration response from Consul is not successful.
        """
        try:
            check_path = (
                check_path if check_path else self.health_path  # type: ignore[reportAttributeAccessIssue]
            )
        except AttributeError as e:
            raise AttributeError(
                "before the consul_register method, call the method that defines "
                "health_path or pass the route explicitly to check_path"
            ) from e
        service_id = f"{self.service_name}:{self.port}"
        http_ = f"http://{self.host}:{self.port}{check_path}"
        payload = {
            "Name": self.service_name,
            "ID": service_id,
            "Port": self.port,
            "Address": self.host,
            "Check": {
                "http": http_,
                "interval": check_interval,
                "timeout": check_timeout,
                "status": "passing",
            },
        }
        block = Block(
            text=[
                "Registration in Consul",
                consul_register_address,
                f"{service_id=}, {self.port=}, {self.host=}",
                f"{check_interval=}, {check_timeout=}",
                f"check path: {http_}",
            ],
            func=CallableWrapper(func=httpx.put, args=[consul_register_address], kwargs={"json": payload}),
        )
        response = block()
        if response.status_code != 200:
            raise ConnectionError(response.text)

    @abstractmethod
    def app_run(self) -> None:
        """
        Abstract method to run the application.

        This method must be implemented in subclasses to start the application.

        Raises:
            NotImplementedError: If the method is not implemented in the subclass.
        """


class AppStarter:
    """
    Class for running the application with Uvicorn or Gunicorn.

    Methods:
        uvicorn_run(asgi_app, host, port): Runs the application with Uvicorn on the specified host and port.
        gunicorn_run(host, port, app_path, workers): Runs the application with Gunicorn, specifying
            the host, port, app path, and number of workers.
    """

    @staticmethod
    @block_decorator(
        ["App Launcher: The setup is completed successfully", "Uvicorn run"], block_type=BlockType.TAIL
    )
    def uvicorn_run(asgi_app, host: str, port: int) -> None:
        """
        Run the application with Uvicorn on the specified host and port.

        Args:
            asgi_app: ASGI application to be run.
            host (str): Host address for the application.
            port (int): Port number on which the application will run.
        """
        import uvicorn

        uvicorn.run(asgi_app, host=host, port=port)

    @staticmethod
    @block_decorator(
        ["App Launcher: The setup is completed successfully", "Gunicorn run"], block_type=BlockType.TAIL
    )
    def gunicorn_run(host: str, port: int, app_path: str, workers: str = "1") -> None:
        """
        Run the application with Gunicorn, specifying the host, port, app path, and number of workers.

        Args:
            host (str): Host address for the application.
            port (int): Port number on which the application will run.
            app_path (str): Path to the application module.
            workers (str): Number of Gunicorn workers to run (default is '1').
        """
        import subprocess

        command = ["gunicorn", "--bind", f"{host}:{port}", "--workers", workers, app_path]
        subprocess.run(command)
