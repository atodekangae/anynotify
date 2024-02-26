# anynotify

anynotify is a flexible, backend-independent error notification system for Python applications. It enables developers to seamlessly integrate error reporting with various notification channels such as Discord.

## Features

- **Backend Independent**: Choose your preferred notification channel.
- **Easy Integration**: Simple setup process for Python applications.
- **Rate-limiting**: Prevent flooding notification channels.

## Quick Start
```python
import anynotify
import logging

anynotify.init(
    integrations=[anynotify.LoggingIntegration()],
    client=anynotify.DiscordClient(webhook_url='https://...'),
)
logging.warning('This will be sent to the Discord channel')
```
