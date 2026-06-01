from asyncio import iscoroutinefunction

from kisna_chatbot.processors.abstract_processor import Processor


class Pipeline:
    """Pipeline class for processing data."""

    def __init__(self, processors: list[Processor]) -> None:
        self.processors = processors

    async def run(self, data: dict) -> dict:
        """Run the pipeline."""
        for processor in self.processors:
            if iscoroutinefunction(processor.process):
                data = await processor.process(data)
            else:
                data = processor.process(data)
        return data
