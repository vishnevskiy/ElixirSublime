defmodule SublimeCompletion.Mixfile do
  use Mix.Project

  def project do
    [
      app: :sublime_completion,
      version: "0.0.1",
      elixir: "~> 1.0",
      deps: deps
    ]
  end

  def application do
    [
      applications: [:logger, :poison],
      mod: {SublimeCompletion, []}
    ]
  end

  defp deps do
    [
      {:poison, "~> 1.3.0"}
    ]
  end
end
