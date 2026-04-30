<a name="readme-top"></a>

<br />
<div>
  <h3 align="center">ytdlp frontend test</h3>

  <p align="center">
    ¯\_(ツ)_/¯<br/>it's what it's
    <br />
    <br />
    <a href="https://ytdlp-vercel.vercel.app">View Demo</a>
    ·
    <a href="https://github.com/FoxeiZ/ytdlp-vercel/issues/new">Report Bug</a>
    ·
    <a href="https://github.com/FoxeiZ/ytdlp-vercel/issues/new">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
      </ul>
    </li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->

## About The Project

Just silly me trying new thing with new tech.

### Built With
<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54" alt="Python" /></a>
  <a href="https://flask.palletsprojects.com/"><img src="https://img.shields.io/badge/flask-%23000.svg?style=for-the-badge&logo=flask&logoColor=white" alt="Flask" /></a>
  <a href="https://jinja.palletsprojects.com/"><img src="https://img.shields.io/badge/jinja-white.svg?style=for-the-badge&logo=jinja&logoColor=black" alt="Jinja" /></a>
  <a href="https://alpinejs.dev/"><img src="https://img.shields.io/badge/alpinejs-77C1D2.svg?style=for-the-badge&logo=alpine.js&logoColor=white" alt="Alpine.js" /></a>
  <a href="https://redis.io/"><img src="https://img.shields.io/badge/redis-%23DD0031.svg?style=for-the-badge&logo=redis&logoColor=white" alt="Redis" /></a>
  <a href="https://developer.mozilla.org/en-US/docs/Web/JavaScript"><img src="https://img.shields.io/badge/js-EFD91C?style=for-the-badge&logo=javascript&logoColor=black" alt="Javascript" /></a>
  <a href="https://ffmpegwasm.netlify.app/"><img src="https://img.shields.io/badge/ffmpeg-white?style=for-the-badge&logo=ffmpeg&logoColor=007808" alt="FFmpeg.wasm" /></a>
</p>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->

## Getting Started

### Prerequisites

- [Python 3.12+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/)

  ```sh
  $ git clone https://github.com/FoxeiZ/ytdlp-vercel
  $ cd ytdlp-vercel
  $ uv sync
  ```

<!-- USAGE EXAMPLES -->

## Usage

You can start the development server using `uv`:

```sh
uv run flask --app src.app run --host 0.0.0.0 --port 3000 --reload --debug
```

Finally, navigate to http://localhost:3000/ and it will automatically show the app.

> The project structure is built to easily deploy on Vercel as a Serverless function.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ROADMAP -->

## Roadmap

- [x] Video
- [x] Audio
- [x] Video and audio merging (need ffmpeg.wasm)
- [x] Responsize
  - [x] Support desktop
  - [x] Support mobile size
- [ ] More f\*

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->

## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- LICENSE -->

## License

Distributed under the GPL 3.0. See `LICENSE.txt` for more information

<p align="right">(<a href="#readme-top">back to top</a>)</p>
