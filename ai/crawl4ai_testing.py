import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

md_generator = DefaultMarkdownGenerator(
    content_filter=PruningContentFilter(threshold=0.4, threshold_type="fixed")
)

config = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    markdown_generator=md_generator
)


async def main():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun("https://docs.crawl4ai.com/", config=config)
        print(result.markdown.raw_markdown[:300])
        print(result.markdown.fit_markdown)

if __name__ == "__main__":
    asyncio.run(main())