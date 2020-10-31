<p align="center"><img src="https://github.com/Shriinivas/etc/blob/master/xnodify/logo.png" alt="logo"/></p><br/>
This Blender Add-on lets user generate material nodes from text expression.

# Version: 0.5 beta

# Installation
- Download the zip file
- In Blneder, go to Edit->Preferences
- Select Add-ons from left hand panel
- Click Install...
- In the Install Add-on dialog select the downloaded zip file and click Install Add-on
- Enable XNodify from add-ons list

# Usage
XNodify panel is available under Edit category in the side-bar of Node Editor.
- Open Node Editor view or select Shading workspace
- Make the side-bar visible (N to toggle side-bar visibility)
- Click on the Edit category
- Type an expression in the Expressions option 
- Click Generate Nodes
<br/>
It's also possible to create multi-line script in Blender text editor, or import an external script file.

# Identifier Lookup

### Math Nodes
<table>
<tr>
<th>Math Operation</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<tr>
<td>Add</td><td>add (or +)</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Subtract</td><td>sub (or -)</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Multiply</td><td>mult (or *)</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Divide</td><td>div (or /)</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Multiply_add</td><td>multadd</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Power</td><td>pow (or **)</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Logarithm</td><td>log</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Sqrt</td><td>sqrt</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Inverse_sqrt</td><td>invsqrt</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Absolute</td><td>abs</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Exponent</td><td>exp</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Minimum</td><td>min</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Maximum</td><td>max</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Less_than</td><td>lt</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Greater_than</td><td>gt</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Sign</td><td>sign</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Compare</td><td>cmp</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Smooth_min</td><td>smthmin</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Smooth_max</td><td>smthmax</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Round</td><td>round</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Floor</td><td>floor</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Ceil</td><td>ceil</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Trunc</td><td>trunc</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Fract</td><td>fract</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Modulo</td><td>mod</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Wrap</td><td>wrap</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Snap</td><td>snap</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Pingpong</td><td>pingpong</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Sine</td><td>sin</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Cosine</td><td>cos</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Tangent</td><td>tan</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Arcsine</td><td>asin</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Arccosine</td><td>acos</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Arctangent</td><td>atan</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Arctan2</td><td>atan2</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Sinh</td><td>sinh</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Cosh</td><td>cosh</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Tanh</td><td>tanh</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Radians</td><td>rad</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Degrees</td><td>deg</td><td>1</td><td>1</td>
</tr>
</table>

### Vector Math Nodes
<table>
<tr>
<th>Vector Operation</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<td>Add</td><td>vadd</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Subtract</td><td>vsub</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Multiply</td><td>vmult</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Divide</td><td>vdiv</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Cross_product</td><td>cross</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Project</td><td>project</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Reflect</td><td>reflect</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Dot_product</td><td>dot</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Distance</td><td>vdist</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Length</td><td>vlen</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Scale</td><td>vscale</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Normalize</td><td>vnorm</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Absolute</td><td>vabs</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Minimum</td><td>vmin</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Maximum</td><td>vmax</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Floor</td><td>vfloor</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Ceil</td><td>vceil</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Fraction</td><td>vfract</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Modulo</td><td>vmod</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Wrap</td><td>wrap</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Snap</td><td>snap</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Sine</td><td>vsin</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Cosine</td><td>vcos</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Tangent</td><td>vtan</td><td>1</td><td>1</td>
</tr>
</table>

### Input Nodes
<table>
<tr>
<th>Node Name</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<td>Ambient Occlusion</td><td>amboccl</td><td>3</td><td>2</td>
</tr>
<tr>
<td>Bevel</td><td>bevel</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Fresnel</td><td>fresnel</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Layer Weight</td><td>layerwt</td><td>2</td><td>2</td>
</tr>
<tr>
<td>Particle Info</td><td>prtclinf</td><td>0</td><td>8</td>
</tr>
<tr>
<td>Wireframe</td><td>wireframe</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Attribute</td><td>attrib</td><td>0</td><td>3</td>
</tr>
<tr>
<td>Camera Data</td><td>camdata</td><td>0</td><td>3</td>
</tr>
<tr>
<td>Geometry</td><td>geom</td><td>0</td><td>9</td>
</tr>
<tr>
<td>Hair Info</td><td>hairinf</td><td>0</td><td>5</td>
</tr>
<tr>
<td>Light Path</td><td>lgtpth</td><td>0</td><td>13</td>
</tr>
<tr>
<td>Object Info</td><td>objinf</td><td>0</td><td>5</td>
</tr>
<tr>
<td>RGB</td><td>shadrgb</td><td>0</td><td>1</td>
</tr>
<tr>
<td>Tangent</td><td>tangent</td><td>0</td><td>1</td>
</tr>
<tr>
<td>Texture Coordinate</td><td>texco</td><td>0</td><td>7</td>
</tr>
<tr>
<td>UV Map</td><td>uvmap</td><td>0</td><td>1</td>
</tr>
<tr>
<td>Value</td><td>value</td><td>0</td><td>1</td>
</tr>
<tr>
<td>Vertex Color</td><td>vertcol</td><td>0</td><td>2</td>
</tr>
<tr>
<td>Volume Info</td><td>volinf</td><td>0</td><td>4</td>
</tr>
</table>

### Output Node
<table>
<tr>
<th>Node Name</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<td>Material Output</td><td>output</td><td>3</td><td>0</td>
</tr>
</table>

### Shader Nodes
<table>
<tr>
<th>Node Name</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<td>Add Shader</td><td>addshad</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Diffuse BSDF</td><td>diffbsdf</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Emission</td><td>emission</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Glass BSDF</td><td>glasbsdf</td><td>4</td><td>1</td>
</tr>
<tr>
<td>Glossy BSDF</td><td>glosbsdf</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Mix Shader</td><td>mixshad</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Principled BSDF</td><td>prnbsdf</td><td>22</td><td>1</td>
</tr>
<tr>
<td>Principled Volume</td><td>prnvol</td><td>12</td><td>1</td>
</tr>
<tr>
<td>Refraction BSDF</td><td>refrbsdf</td><td>4</td><td>1</td>
</tr>
<tr>
<td>Specular</td><td>specular</td><td>10</td><td>1</td>
</tr>
<tr>
<td>Subsurface Scattering</td><td>subsrfsct</td><td>5</td><td>1</td>
</tr>
<tr>
<td>Translucent BSDF</td><td>tcntbsdf</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Transparent BSDF</td><td>tpntbsdf</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Volume Absorption</td><td>volabs</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Volume Scatter</td><td>volscat</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Holdout</td><td>holdout</td><td>0</td><td>1</td>
</tr>
</table>

### Texture Nodes
<table>
<tr>
<th>Node Name</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<td>Brick Texture</td><td>brcktex</td><td>10</td><td>2</td>
</tr>
<tr>
<td>Checker Texture</td><td>chctex</td><td>4</td><td>2</td>
</tr>
<tr>
<td>Environment Texture</td><td>envtex</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Gradient Texture</td><td>gradtex</td><td>1</td><td>2</td>
</tr>
<tr>
<td>IES Texture</td><td>iestex</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Image Texture</td><td>imgtex</td><td>1</td><td>2</td>
</tr>
<tr>
<td>Magic Texture</td><td>magictex</td><td>3</td><td>2</td>
</tr>
<tr>
<td>Musgrave Texture</td><td>mustex</td><td>5</td><td>1</td>
</tr>
<tr>
<td>Noise Texture</td><td>noisetex</td><td>5</td><td>2</td>
</tr>
<tr>
<td>Point Density</td><td>ptdnsty</td><td>1</td><td>2</td>
</tr>
<tr>
<td>Sky Texture</td><td>skytex</td><td>0</td><td>1</td>
</tr>
<tr>
<td>Voronoi Texture</td><td>vorntex</td><td>3</td><td>3</td>
</tr>
<tr>
<td>Wave Texture</td><td>wavetex</td><td>7</td><td>2</td>
</tr>
<tr>
<td>White Noise Texture</td><td>whnsetex</td><td>1</td><td>2</td>
</tr>
</table>

### Color Nodes
<table>
<tr>
<th>Node Name</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<td>Bright/Contrast</td><td>brtcst</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Gamma</td><td>gamma</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Hue Saturation Value</td><td>hsval</td><td>5</td><td>1</td>
</tr>
<tr>
<td>Invert</td><td>invert</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Light Falloff</td><td>ltfloff</td><td>2</td><td>3</td>
</tr>
<tr>
<td>Mix</td><td>mixrgb</td><td>3</td><td>1</td>
</tr>
<tr>
<td>RGB Curves</td><td>rgbcrvs</td><td>2</td><td>1</td>
</tr>
</table>

### Vector Nodes
<table>
<tr>
<th>Node Name</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<td>Bump</td><td>bump</td><td>4</td><td>1</td>
</tr>
<tr>
<td>Displacement</td><td>disp</td><td>4</td><td>1</td>
</tr>
<tr>
<td>Mapping</td><td>mapping</td><td>4</td><td>1</td>
</tr>
<tr>
<td>Normal</td><td>normal</td><td>1</td><td>2</td>
</tr>
<tr>
<td>Normal Map</td><td>normmap</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Vector Curves</td><td>vctcrvs</td><td>2</td><td>1</td>
</tr>
<tr>
<td>Vector Displacement</td><td>vctdisp</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Vector Rotate</td><td>vctrot</td><td>4</td><td>1</td>
</tr>
<tr>
<td>Vector Transform</td><td>vcttrns</td><td>1</td><td>1</td>
</tr>
</table>

### converter Nodes
<table>
<tr>
<th>Node Name</th><th>Identifier</th><th>Input Count</th><th>Output Count</th>
</tr>
<tr>
<td>Blackbody</td><td>blkbody</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Clamp</td><td>clamp</td><td>3</td><td>1</td>
</tr>
<tr>
<td>ColorRamp</td><td>colramp</td><td>1</td><td>2</td>
</tr>
<tr>
<td>Combine HSV</td><td>comhsv</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Combine RGB</td><td>comrgb</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Combine XYZ</td><td>comxyz</td><td>3</td><td>1</td>
</tr>
<tr>
<td>Map Range</td><td>maprange</td><td>5</td><td>1</td>
</tr>
<tr>
<td>RGB to BW</td><td>rgb2bw</td><td>1</td><td>1</td>
</tr>
<tr>
<td>Separate HSV</td><td>sephsv</td><td>1</td><td>3</td>
</tr>
<tr>
<td>Separate RGB</td><td>seprgb</td><td>1</td><td>3</td>
</tr>
<tr>
<td>Separate XYZ</td><td>sepxyz</td><td>1</td><td>3</td>
</tr>
<tr>
<td>Shader to RGB</td><td>shd2rgb</td><td>1</td><td>2</td>
</tr>
<tr>
<td>Wavelength</td><td>wvlngth</td><td>1</td><td>1</td>
</tr>
</table>
