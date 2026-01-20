import os
from typing import List

from .logger import get_logger

logger = get_logger()


class ConsoleUI:
    def echo(self, message: str = "", err: bool = False) -> None:
        if err:
            logger.error(message)
        else:
            logger.info(message)

    def info(self, message: str) -> None:
        self.echo(message)

    def warn(self, message: str) -> None:
        self.echo(message, err=True)

    def error(self, message: str) -> None:
        self.echo(message, err=True)

    def box_output(self, lines: List[str], err: bool = False) -> None:
        self.echo("", err=err)
        for line in lines:
            self.echo(line, err=err)
        self.echo("", err=err)

    def prompt(self, message: str = "") -> str:
        return input(message)

    def clear(self) -> None:
        os.system("cls")


ui = ConsoleUI()
