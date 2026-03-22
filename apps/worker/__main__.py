from libs.core.config import get_config
from libs.core.logging import configure_logging
from libs.core.policy import SYSTEM_ACTOR
from libs.orchestration.worker import run_worker_forever
from libs.storage.session import get_session_factory, initialize_database


def main() -> None:
    config = get_config()
    configure_logging(config.env)
    if config.auto_init_db:
        initialize_database(config)
    session_factory = get_session_factory(config)
    run_worker_forever(session_factory, config, SYSTEM_ACTOR)


if __name__ == "__main__":
    main()

