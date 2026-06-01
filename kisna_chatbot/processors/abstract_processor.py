from abc import abstractmethod


class Processor:
    """Defines a framework for asynchronous data processing on data of type T.

    This abstract class provides a template for defining specific processing behaviors
    tailored to various types of input data. Each subclass should implement the
    asynchronous process method, facilitating non-blocking data manipulation suitable
    for I/O-bound tasks.
    """

    @abstractmethod
    def should_run(self, data: dict) -> bool:
        """Determines whether the processor should run based on the input data.

        This method should be overridden to include specific logic that evaluates the
        input data and decides whether the processor should be executed. It allows for
        conditional processing based on the data content, metadata, or other relevant
        factors.

        Args:
            data: An instance of type dict, representing the input data to be processed.

        Returns:
            A boolean value indicating whether the processor should run or not.
        """
        pass

    @abstractmethod
    async def process(self, data: dict) -> dict:
        """Asynchronously transforms the input data based on defined processing rules.

        This method should be overridden to include specific logic that manipulates the
        data, potentially involving I/O operations such as fetching, modifying, and
        returning data. It ensures that the data handling is performed asynchronously
        to optimize performance.

        Args:
            data: An instance of type T, representing the data to be processed.

        Returns:
            An instance of type T, representing the transformed or processed data.
        """
        pass
