# Template of the Homebrew formula of OpenGuildKit, for a tap the maintainer owns (docs/install.md, "Package
# managers"). `python scripts/release_manifests.py --sums SHA256SUMS.txt --output DIR` writes it with the version,
# url and sha256 of the wheel of a release; nothing here is published.
#
# The release ships a wheel and no source distribution, so the formula installs that wheel into a virtualenv with
# the helpers of Language::Python::Virtualenv. `virtualenv_install_with_resources` installs the unpacked
# buildpath and needs a source tree; the wheel has no dependency, so there is no resource block.
# https://docs.brew.sh/Language-Specific-Formulae#python (read 2026-11-28)
class Openguildkit < Formula
  include Language::Python::Virtualenv

  desc "Project rules and specialist reviews for AI-assisted work"
  homepage "https://github.com/@REPOSITORY@"
  url "@WHEEL_URL@", using: :nounzip
  version "@VERSION@"
  sha256 "@WHEEL_SHA256@"
  license "MIT"

  depends_on "python@3.14"

  def install
    venv = virtualenv_create(libexec, "python3.14")
    venv.pip_install_and_link Dir["openguildkit-*-py3-none-any.whl"]
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/openguildkit --version")
  end
end
