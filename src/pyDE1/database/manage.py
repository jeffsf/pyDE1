"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import asyncio
import logging
import sqlite3
import subprocess
from datetime import datetime
from multiprocessing import cpu_count
from pathlib import Path
from typing import Union, Optional

import pyDE1
from pyDE1.config import config
from pyDE1.exceptions import DE1DBError

logger = pyDE1.getLogger('Database.Manage')

CURRENT_USER_VERSION = 2
CURRENT_SCHEMA_RELPATH = 'schema/schema.002.sql'


def check_schema(loop: Optional[asyncio.AbstractEventLoop] = None):
    db_file_existed = Path(config.database.FILENAME).is_file()
    if not db_file_existed:
        logger.info(
            f"Database does not exist, will create {config.database.FILENAME}")
    try:
        with sqlite3.connect(config.database.FILENAME) as db:
            cur = db.execute('PRAGMA user_version')
            user_version = cur.fetchone()[0]
            if user_version == CURRENT_USER_VERSION:
                logger.debug(f"Confirmed user_version {user_version}")
            elif user_version:
                msg = (f"Database needs upgrade from {user_version} "
                       f"to {CURRENT_USER_VERSION}. Exiting.")
                logger.critical(msg)
                raise DE1DBError(msg)
            else:
                if db_file_existed:
                    bu_fname = '{}.{}.backup'.format(
                        config.database.FILENAME,
                        datetime.now().isoformat(timespec='seconds'),
                    )
                    backup_db(config.database.FILENAME, bu_fname,  loop)
                schema_path = Path(__file__).resolve().parent.joinpath(
                    CURRENT_SCHEMA_RELPATH).resolve()
                logger.info(
                    f"No user_version found. Installing schema from {schema_path}")
                schema = sql_commands_from_file(schema_path)
                logger.debug(f"Read {len(schema)} commands from {schema_path}")
                for sql in schema:
                    db.execute(sql)
                db.commit()
                logger.info("Initalization executed")
    except sqlite3.OperationalError as e:
        logger.critical(f"Database schema failed, aborting: {e}",
                        exc_info=e)
        raise DE1DBError(e)


def sql_commands_from_file(filename: Union[Path, str]) -> list:
    # This is "close" in that it should catch "common usage"
    # but might miss things, such as when literals contain the delimiters
    with open(filename, 'r') as sf:
        lines = sf.readlines()
    uncommented = []
    in_block_comment = False
    for line in lines:
        line = line.rstrip('\r\n')
        if not in_block_comment:
            idx_block_comment_start = line.find('/*')
            idx_eol_comment_start = line.find('--')
            if (    idx_block_comment_start == -1
                and idx_eol_comment_start == -1):
                if len(line.strip()):
                    uncommented.append(line)
            # From here on, one or both are present
            elif idx_block_comment_start == -1 \
                    or idx_eol_comment_start < idx_block_comment_start:
                # This is an EOL-style comment
                rest = line[0:idx_eol_comment_start]
                if len(rest.strip()):
                    uncommented.append(rest)
            elif idx_eol_comment_start == -1 \
                    or idx_block_comment_start < idx_eol_comment_start:
                # This is block-style comment start
                rest = line[0:idx_block_comment_start]
                if len(rest.strip()):
                    uncommented.append(rest)
                in_block_comment = True
            else:
                raise DE1DBError(
                    "Unexpected logic error in comment removal in SQL. "
                    f"idx_eol: {idx_eol_comment_start} "
                    f"idx_block: {idx_block_comment_start}")
        else:
            idx_block_comment_end = line.find('*/')
            if idx_block_comment_end != -1:
                uncommented.append(line[(idx_block_comment_end+2):])
                in_block_comment = False
            else:
                pass

    uncommented[-1] = (uncommented[-1].rstrip()).rstrip(';')

    # retval = ('\n'.join(uncommented)).split(';\n')
    return (' '.join(uncommented)).split('; ')


def backup_db(db_filename: str, backup_filename: str,
              loop: Optional[asyncio.AbstractEventLoop] = None):
    if Path(backup_filename).exists():
        msg = (f"Destination exists {backup_filename}, "
               f"aborting backup of {db_filename}")
        logger.critical(msg)
        raise DE1DBError(msg)

    logger.info(
        f"Backing up {db_filename} to {backup_filename}, "
        f"{config.database.BACKUP_TIMEOUT} s timeout."
    )

    try:
        cp = subprocess.run(
            ['sqlite3', db_filename, f".backup {backup_filename}"],
            capture_output=True,
            check=True,
            timeout=config.database.BACKUP_TIMEOUT,
        )
    except subprocess.CalledProcessError as e:
        logger.critical(
            f"Unable to backup {db_filename} to {backup_filename}, "
            f"{e}. Aborting\n"
            f"stderr: {e.stderr.decode('utf-8')}\n"
            f"stdout: {e.stdout.decode('utf-8')}\n"
        )
        raise DE1DBError(e)
    except subprocess.TimeoutExpired as e:
        logger.critical(
            f"Timeout during backup {db_filename} to {backup_filename}, "
            f"{e}. Aborting"
        )
        raise DE1DBError(e)

    logger.info(f"Backed up to {backup_filename}")

    if loop is not None:
        cpu_min = 2
        if cpu_count() >= cpu_min:
            logger.info(f"Scheduling compression of {backup_filename}")
            t_compress = loop.run_in_executor(
                None,
                subprocess.run,
                [config.database.BACKUP_COMPRESSION_EXECUTABLE,
                 backup_filename],
            )

            def tdc(fut: asyncio.Future):
                if fut.exception():
                    logger.warning("Compression task failed")
                else:
                    res: subprocess.CompletedProcess = fut.result()
                    if res.returncode:
                        logger.warning(
                            f"Compression execution error: {res.returncode}")

            t_compress.add_done_callback(tdc)
        else:
            logger.warning(
                f"NOT scheduling compression of {backup_filename} "
                f"with less than {cpu_min} CPU(s)")


if __name__ == '__main__':
    format_string = "%(asctime)s %(levelname)s %(name)s: %(message)s"

    logging.basicConfig(level=logging.DEBUG,
                        format=format_string,
                        )

    # pprint.pprint(
    #     sql_commands_from_file(
    #         '/home/ble-remote/devel/pyDE1/src/pyDE1/database/schema/schema.002.sql')
    # )

    config.load_from_yaml('/usr/local/etc/pyde1/pyde1.config')

    backup_db('/var/lib/pyde1/pyde1.sqlite3', '/home/ble-remote/bu.backup',
              asyncio.get_event_loop())