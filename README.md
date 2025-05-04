![img](https://github.com/GeiserX/askepub/blob/main/extra/logo.jpg?raw=true)
# AskePub

[![askepub compliant](https://img.shields.io/github/license/GeiserX/askepub)](https://github.com/GeiserX/askepub/blob/main/LICENSE)

This project is a Telegram bot assistant to help you prepare ePubs. It uses ChatGPT-4o to write contextual notes.

## Table of Contents

- [Install](#install)
- [Usage](#usage)
- [Maintainers](#maintainers)
- [Contributing](#contributing)

## Install

This project uses a [Docker container](https://hub.docker.com/repository/docker/drumsergio/askepub) to deploy a Telegram Bot handler.

```sh
$ docker run --name askepub -e TOKEN=[TOKEN] -e OPENAI_API_KEY=[KEY] drumsergio/askepub
```

Docker Hub image available at [drumsergio/askepub](https://hub.docker.com/repository/docker/drumsergio/askepub).

## Usage

Use the command `/start` and follow the prompts

## Maintainers

[@GeiserX](https://github.com/GeiserX).

## Contributing

Feel free to dive in! [Open an issue](https://github.com/GeiserX/askepub/issues/new) or submit PRs.

AskePub follows the [Contributor Covenant](http://contributor-covenant.org/version/2/1/) Code of Conduct.

### Contributors

This project exists thanks to all the people who contribute. 
<a href="https://github.com/GeiserX/askepub/graphs/contributors"><img src="https://opencollective.com/askepub/contributors.svg?width=890&button=false" /></a>


