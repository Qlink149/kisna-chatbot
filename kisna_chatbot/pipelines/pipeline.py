import time
from asyncio import iscoroutinefunction

from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import log_event, logger


class Pipeline:
    """Pipeline class for processing data."""

    def __init__(self, processors: list[Processor]) -> None:
        self.processors = processors

    async def run(self, data: dict) -> dict:
        """Run the pipeline."""
        pipeline_name = self.__class__.__name__
        phone_number = data.get("phone_number")
        service_selected = (data.get("user_profile") or {}).get("service_selected")
        pipeline_start = time.perf_counter()

        log_event(
            "pipeline_start",
            pipeline_name,
            pipeline=pipeline_name,
            phone_number=phone_number,
            service_selected=service_selected or None,
        )

        try:
            for processor in self.processors:
                processor_name = processor.__class__.__name__
                proc_start = time.perf_counter()
                log_event(
                    "processor_start",
                    processor_name,
                    pipeline=pipeline_name,
                    processor=processor_name,
                    phone_number=phone_number,
                )
                try:
                    if iscoroutinefunction(processor.process):
                        data = await processor.process(data)
                    else:
                        data = processor.process(data)
                except Exception:
                    logger.exception(
                        "Processor failed",
                        extra={
                            "event": "processor_error",
                            "pipeline": pipeline_name,
                            "processor": processor_name,
                            "phone_number": phone_number,
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - proc_start) * 1000)
                log_event(
                    "processor_done",
                    processor_name,
                    pipeline=pipeline_name,
                    processor=processor_name,
                    phone_number=phone_number,
                    duration_ms=duration_ms,
                )

            total_ms = int((time.perf_counter() - pipeline_start) * 1000)
            log_event(
                "pipeline_done",
                pipeline_name,
                pipeline=pipeline_name,
                phone_number=phone_number,
                duration_ms=total_ms,
            )
            return data
        except Exception:
            total_ms = int((time.perf_counter() - pipeline_start) * 1000)
            logger.exception(
                "Pipeline failed",
                extra={
                    "event": "pipeline_error",
                    "pipeline": pipeline_name,
                    "phone_number": phone_number,
                    "duration_ms": total_ms,
                },
            )
            raise
