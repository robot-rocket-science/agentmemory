# ASCII Rendering Reference

Source: https://alexharri.com/blog/ascii-rendering

## Core Concept

Render images as ASCII art while maintaining sharp edges by treating characters as shapes rather than pixels.

## The Problem with Standard ASCII Rendering

Traditional image-to-ASCII conversion uses "nearest-neighbor downsampling," sampling a single pixel at each grid cell's center. This creates jagged edges because characters are treated as uniform blocks. "This blurriness happens because the ASCII characters are being treated like pixels -- their shape is ignored."

## The Solution: 6-Dimensional Shape Vectors

Rather than reducing characters to single lightness values, quantify each character's visual density across multiple regions:

**Sampling circles** are placed strategically within each grid cell to measure how much visual weight characters carry in different areas. Initially using 2 dimensions (upper/lower regions), expanded to 6 dimensions to capture left-right variation and middle occupancy.

### How It Works:

1. **Generate character shape vectors** once during setup by sampling overlap between each ASCII character and the measurement circles
2. **For each grid cell**, collect samples from the image being rendered in corresponding circles
3. **Find nearest match** using Euclidean distance in 6D space -- the character whose shape best matches the cell's content

## Performance Optimization

The brute-force nearest-neighbor lookup proved too slow for animation. Two solutions:

- **k-d trees**: Spatial data structures for efficient multidimensional searching (~100x faster)
- **Caching**: Quantizing vector components to 5 bits each, packing into single numbers for hash-based lookup

## Contrast Enhancement

To sharpen boundaries between different regions, apply power functions to sampling vectors, darkening lower values while preserving highlights. "Directional contrast enhancement" uses external sampling circles from neighboring cells to enhance edges further, preventing staircasing artifacts.

## Results

The method produces crisp ASCII art where character selection follows shape contours precisely, with readable edge definition and smooth gradients.
