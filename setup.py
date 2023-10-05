from setuptools import setup

with open('README.md') as f:
    long_description = f.read()

setup(name='UniswapPy',
      version='1.0.6',
      description='Uniswap for Python',
      long_description=long_description,
      long_description_content_type="text/markdown",
      url='http://github.com/icmoore/uniswappy',
      author = "icmoore",
      author_email = "imoore@syscoin.org",
      license='MIT',
      package_dir = {"uniswappy": "python/prod"},
      packages=[
          'uniswappy.cpt.exchg',
          'uniswappy.cpt.factory',
          'uniswappy.cpt.index',
          'uniswappy.cpt.quote',
          'uniswappy.cpt.wallet',
          'uniswappy.erc',
          'uniswappy.math.basic',
          'uniswappy.math.basic',
          'uniswappy.math.interest',
          'uniswappy.math.interest.ips',
          'uniswappy.math.interest.ips.aggregate',
          'uniswappy.math.model',
          'uniswappy.math.risk',
          'uniswappy.process',
          'uniswappy.process.deposit',
          'uniswappy.process.deposit',
          'uniswappy.process.liquidity',
          'uniswappy.process.swap',
          'uniswappy.simulate',   
          'python.prod.cpt.exchg',
          'python.prod.cpt.factory',
          'python.prod.cpt.index',
          'python.prod.cpt.quote',
          'python.prod.cpt.wallet',
          'python.prod.erc',
          'python.prod.math.basic',
          'python.prod.math.basic',
          'python.prod.math.interest',
          'python.prod.math.interest.ips',
          'python.prod.math.interest.ips.aggregate',
          'python.prod.math.model',
          'python.prod.math.risk',
          'python.prod.process',
          'python.prod.process.deposit',
          'python.prod.process.deposit',
          'python.prod.process.liquidity',
          'python.prod.process.swap',
          'python.prod.simulate',
      ],
      zip_safe=False)
