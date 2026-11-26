"""일관된 전체 핑거프린트 프로필: macOS / Windows + 서울 신원.

pydoll 저장소의 examples/fingerprints.py 중 ``macos_m3_new_york`` 프로필을 기반으로,
이 프로젝트의 실행 환경(macOS 의 실제 Chrome, 한국 IP)에 맞게 고친 것이다.

프로필이 탐지되지 않으려면 두 가지가 맞아야 한다.

1. UA 의 Chrome 버전 = 실제로 띄운 Chrome 바이너리.
   네트워크 계층 지문(TLS JA3/JA4, HTTP/2 SETTINGS)은 진짜 브라우저에서 나오고 위장할 수
   없다. 그래서 버전을 하드코딩하지 않고 ``build_macos_seoul_profile()`` 에 인자로 받는다.

2. 언어·시간대·위치 = 출구 IP(또는 프록시)의 지역.
   다른 나라 프록시를 쓴다면 LOCALE / TIMEZONE / GEOLOCATION / SPEECH 를 그 나라에 맞게 바꾼다.

Windows 에서 실행하면 같은 방식으로 만든 Windows 프로필(``build_windows_seoul_profile``)을
쓴다. ``build_full_profile()`` 이 실행 중인 OS 에 맞는 것을 고른다.

OS 는 실제 기기와 같게 둔다. TCP 지문, 폰트 렌더링, 설치된 폰트는 호스트 OS 에서
나오므로 Mac 에서 Windows 프로필을 쓰면 오히려 드러난다.
"""

import platform
import sys

from pydoll.protocol.fingerprint.types import (
    AudioFingerprint,
    ClientHintsFingerprint,
    FingerprintConfig,
    FontFingerprint,
    GeolocationFingerprint,
    HardwareFingerprint,
    LocaleFingerprint,
    MediaCodecsFingerprint,
    MediaDevicesFingerprint,
    MediaFeaturesFingerprint,
    NavigatorFingerprint,
    NetworkConnectionFingerprint,
    PermissionsFingerprint,
    PlatformApisFingerprint,
    ScreenFingerprint,
    SpeechFingerprint,
    SpeechVoice,
    WebGLProfile,
    WebGPUProfile,
)

# --- 지역 신원 (출구 IP 지역과 일치시킬 것) -----------------------------------

LANGUAGES = ['ko-KR', 'ko', 'en-US', 'en']
TIMEZONE = 'Asia/Seoul'

LOCALE = LocaleFingerprint(languages=LANGUAGES)
GEOLOCATION = GeolocationFingerprint(latitude=37.5665, longitude=126.9780, accuracy=100.0)

# macOS 한국어 환경의 음성: 시스템 음성(Yuna) + 기본 영어 음성 + Chrome 의 Google 원격 음성.
SPEECH = SpeechFingerprint(
    voices=[
        SpeechVoice(name='Yuna', lang='ko-KR', local_service=True),
        SpeechVoice(name='Samantha', lang='en-US', local_service=True),
        SpeechVoice(name='Google 한국의', lang='ko-KR', local_service=False),
        SpeechVoice(name='Google US English', lang='en-US', local_service=False),
    ]
)

# --- 기기 신원 (MacBook Air M3 급) --------------------------------------------

# 창 크기. 브라우저 실행 옵션(--window-size)도 이 값과 맞춘다.
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 860

SCREEN = ScreenFingerprint(
    width=1440,
    height=900,
    avail_width=1440,
    avail_height=860,
    avail_top=25,  # 상단 메뉴 막대. 나머지 15 는 Dock
    avail_left=0,
    outer_width=WINDOW_WIDTH,
    outer_height=WINDOW_HEIGHT,
    inner_width=1440,
    inner_height=785,
    color_depth=24,
    pixel_depth=24,
    device_pixel_ratio=2.0,  # Retina
    orientation_type='landscape-primary',
    orientation_angle=0,
)

HARDWARE = HardwareFingerprint(hardware_concurrency=8, device_memory=8, max_touch_points=0)

# 폰트 폭 측정 방식의 탐지는 레이아웃 엔진을 직접 읽어 덮어쓸 수 없다.
# 따라서 이 Mac 에 실제로 설치된 폰트만 나열한다 (macOS 기본 폰트 + 한글 폰트).
FONTS = FontFingerprint(
    available_fonts=[
        'Apple SD Gothic Neo',
        'AppleGothic',
        'AppleMyungjo',
        'Arial',
        'Arial Black',
        'Comic Sans MS',
        'Courier New',
        'Georgia',
        'Helvetica',
        'Helvetica Neue',
        'Impact',
        'Lucida Grande',
        'Menlo',
        'Monaco',
        'Palatino',
        'Tahoma',
        'Times New Roman',
        'Trebuchet MS',
        'Verdana',
    ]
)

# --- 아래 상수들은 pydoll examples/fingerprints.py 에서 그대로 가져온 값 --------

SHADER_PRECISION_DEFAULT = {
    'vertex': {
        'highFloat': [127, 127, 23],
        'mediumFloat': [15, 15, 10],
        'lowFloat': [15, 15, 10],
        'highInt': [31, 30, 0],
        'mediumInt': [15, 14, 0],
        'lowInt': [15, 14, 0],
    },
    'fragment': {
        'highFloat': [127, 127, 23],
        'mediumFloat': [15, 15, 10],
        'lowFloat': [15, 15, 10],
        'highInt': [31, 30, 0],
        'mediumInt': [15, 14, 0],
        'lowInt': [15, 14, 0],
    },
}

WEBGPU_APPLE_M_SERIES = WebGPUProfile(
    vendor='apple',
    architecture='metal-3',
    device='',
    description='',
    limits={
        'maxTextureDimension1D': 16384,
        'maxTextureDimension2D': 16384,
        'maxTextureDimension3D': 2048,
        'maxTextureArrayLayers': 2048,
        'maxBindGroups': 4,
        'maxBindGroupsPlusVertexBuffers': 24,
        'maxBindingsPerBindGroup': 1000,
        'maxDynamicUniformBuffersPerPipelineLayout': 10,
        'maxDynamicStorageBuffersPerPipelineLayout': 8,
        'maxSampledTexturesPerShaderStage': 48,
        'maxSamplersPerShaderStage': 16,
        'maxStorageBuffersPerShaderStage': 10,
        'maxStorageTexturesPerShaderStage': 8,
        'maxUniformBuffersPerShaderStage': 12,
        'maxUniformBufferBindingSize': 65536,
        'maxStorageBufferBindingSize': 4294967292,
        'minUniformBufferOffsetAlignment': 256,
        'minStorageBufferOffsetAlignment': 256,
        'maxVertexBuffers': 8,
        'maxBufferSize': 4294967292,
        'maxVertexAttributes': 30,
        'maxVertexBufferArrayStride': 2048,
        'maxInterStageShaderVariables': 28,
        'maxColorAttachments': 8,
        'maxColorAttachmentBytesPerSample': 128,
        'maxComputeWorkgroupStorageSize': 32768,
        'maxComputeInvocationsPerWorkgroup': 1024,
        'maxComputeWorkgroupSizeX': 1024,
        'maxComputeWorkgroupSizeY': 1024,
        'maxComputeWorkgroupSizeZ': 64,
        'maxComputeWorkgroupsPerDimension': 65535,
        'maxImmediateSize': 64,
        'maxStorageBuffersInFragmentStage': 10,
        'maxStorageTexturesInFragmentStage': 8,
        'maxStorageBuffersInVertexStage': 10,
        'maxStorageTexturesInVertexStage': 8,
    },
    features=[
        'depth32float-stencil8',
        'rg11b10ufloat-renderable',
        'bgra8unorm-storage',
        'texture-formats-tier1',
        'texture-compression-bc',
        'dual-source-blending',
        'core-features-and-limits',
        'float32-filterable',
        'indirect-first-instance',
        'texture-compression-astc-sliced-3d',
        'float32-blendable',
        'subgroup-size-control',
        'texture-compression-astc',
        'texture-compression-etc2',
        'depth-clip-control',
        'texture-compression-bc-sliced-3d',
        'clip-distances',
        'texture-formats-tier2',
        'shader-f16',
        'timestamp-query',
        'primitive-index',
        'texture-component-swizzle',
        'subgroups',
    ],
)

DESKTOP_CHROMIUM_CODECS = MediaCodecsFingerprint(
    can_play_type={
        'video/mp4; codecs="avc1.42E01E"': 'probably',
        'video/webm; codecs="vp8"': 'probably',
        'video/webm; codecs="vp9"': 'probably',
        'video/ogg; codecs="theora"': '',
        'video/quicktime': '',
        'video/x-matroska': 'maybe',
        'audio/aac': 'probably',
        'audio/mpeg': 'probably',
        'audio/mpegurl': 'maybe',
        'audio/ogg; codecs="vorbis"': 'probably',
        'audio/wav; codecs="1"': 'probably',
        'audio/x-m4a': 'maybe',
    },
    media_source={
        'video/mp4; codecs="avc1.42E01E"': True,
        'video/webm; codecs="vp8"': True,
        'video/webm; codecs="vp9"': True,
        'video/ogg; codecs="theora"': False,
        'video/quicktime': False,
        'video/x-matroska': False,
        'audio/aac': True,
        'audio/mpeg': True,
        'audio/mpegurl': False,
        'audio/ogg; codecs="vorbis"': False,
        'audio/wav; codecs="1"': False,
        'audio/x-m4a': False,
    },
)

DESKTOP_NETWORK = NetworkConnectionFingerprint(
    effective_type='4g',
    downlink=10.0,
    rtt=50,
    save_data=False,
)

DESKTOP_PERMISSIONS = PermissionsFingerprint(
    overrides={
        'notifications': 'denied',
        'geolocation': 'prompt',
        'camera': 'prompt',
        'microphone': 'prompt',
    }
)

MACOS_ABSENT_APIS = [
    'ContactsManager',
    'ContentIndex',
    'navigator.contacts',
    'NetworkInformation.downlinkMax',
]

WEBGL = WebGLProfile(
    vendor='Google Inc. (Apple)',
    renderer='ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)',
    max_texture_size=16384,
    max_renderbuffer_size=16384,
    max_viewport_dims=[16384, 16384],
    max_vertex_attribs=16,
    max_vertex_uniform_vectors=1024,
    max_vertex_uniform_components=4096,
    max_fragment_uniform_vectors=1024,
    max_fragment_uniform_components=4096,
    max_varying_vectors=30,
    max_varying_components=120,
    max_vertex_output_components=120,
    max_fragment_input_components=120,
    max_texture_image_units=16,
    max_vertex_texture_image_units=16,
    max_combined_texture_image_units=32,
    max_uniform_block_size=16384,
    max_uniform_buffer_bindings=32,
    max_vertex_uniform_blocks=16,
    max_fragment_uniform_blocks=16,
    max_combined_uniform_blocks=32,
    max_combined_vertex_uniform_components=69632,
    max_combined_fragment_uniform_components=69632,
    uniform_buffer_offset_alignment=16,
    max_texture_lod_bias=15.0,
    max_transform_feedback_interleaved_components=128,
    aliased_line_width_range=[1, 1],
    aliased_point_size_range=[1, 511],
    shader_precision_formats=SHADER_PRECISION_DEFAULT,
)

# --- Windows 기기 신원 (Windows 11 데스크톱, RTX 3060 급) -----------------------
# pydoll examples/fingerprints.py 의 ``windows11_rtx3060_nyc`` 를 서울 신원으로 고친 것.
# Windows 에서 실행할 때만 쓴다 (Mac 에서 쓰면 폰트·TCP 지문으로 드러난다).

WINDOWS_WINDOW_WIDTH = 1920
WINDOWS_WINDOW_HEIGHT = 1040

WINDOWS_SCREEN = ScreenFingerprint(
    width=1920,
    height=1080,
    avail_width=1920,
    avail_height=1040,
    avail_top=0,  # 작업 표시줄은 아래쪽
    avail_left=0,
    outer_width=WINDOWS_WINDOW_WIDTH,
    outer_height=WINDOWS_WINDOW_HEIGHT,
    inner_width=1903,
    inner_height=969,
    color_depth=24,
    pixel_depth=24,
    device_pixel_ratio=1.0,
    orientation_type='landscape-primary',
    orientation_angle=0,
)

WINDOWS_HARDWARE = HardwareFingerprint(
    hardware_concurrency=12, device_memory=8, max_touch_points=0
)

# 한국어 Windows 의 음성: 시스템 음성(Heami) + Chrome 의 Google 원격 음성.
WINDOWS_SPEECH = SpeechFingerprint(
    voices=[
        SpeechVoice(name='Microsoft Heami - Korean (Korean)', lang='ko-KR', local_service=True),
        SpeechVoice(name='Google 한국의', lang='ko-KR', local_service=False),
        SpeechVoice(name='Google US English', lang='en-US', local_service=False),
    ]
)

# Windows 기본 폰트 + 한국어 Windows 의 한글 폰트.
# 영문 Windows 에는 한글 폰트(굴림·돋움·바탕·궁서)가 없을 수 있다. 없으면 목록에서 지운다.
WINDOWS_FONTS = FontFingerprint(
    available_fonts=[
        'Arial',
        'Arial Black',
        'Batang',
        'Calibri',
        'Cambria',
        'Comic Sans MS',
        'Consolas',
        'Courier New',
        'Dotum',
        'Georgia',
        'Gulim',
        'Gungsuh',
        'Impact',
        'Lucida Console',
        'Malgun Gothic',
        'Microsoft Sans Serif',
        'Palatino Linotype',
        'Segoe UI',
        'Tahoma',
        'Times New Roman',
        'Trebuchet MS',
        'Verdana',
    ]
)

DESKTOP_EXTENSIONS = [
    'ANGLE_instanced_arrays',
    'EXT_blend_minmax',
    'EXT_clip_control',
    'EXT_color_buffer_half_float',
    'EXT_depth_clamp',
    'EXT_disjoint_timer_query',
    'EXT_float_blend',
    'EXT_frag_depth',
    'EXT_shader_texture_lod',
    'EXT_texture_compression_bptc',
    'EXT_texture_compression_rgtc',
    'EXT_texture_filter_anisotropic',
    'EXT_texture_mirror_clamp_to_edge',
    'EXT_sRGB',
    'KHR_parallel_shader_compile',
    'OES_element_index_uint',
    'OES_fbo_render_mipmap',
    'OES_standard_derivatives',
    'OES_texture_float',
    'OES_texture_float_linear',
    'OES_texture_half_float',
    'OES_texture_half_float_linear',
    'OES_vertex_array_object',
    'WEBGL_color_buffer_float',
    'WEBGL_compressed_texture_s3tc',
    'WEBGL_compressed_texture_s3tc_srgb',
    'WEBGL_debug_renderer_info',
    'WEBGL_debug_shaders',
    'WEBGL_depth_texture',
    'WEBGL_draw_buffers',
    'WEBGL_lose_context',
    'WEBGL_multi_draw',
    'WEBGL_polygon_mode',
]

DESKTOP_WEBGL2_EXTENSIONS = [
    'EXT_clip_control',
    'EXT_color_buffer_float',
    'EXT_color_buffer_half_float',
    'EXT_conservative_depth',
    'EXT_depth_clamp',
    'EXT_float_blend',
    'EXT_render_snorm',
    'EXT_texture_compression_bptc',
    'EXT_texture_compression_rgtc',
    'EXT_texture_filter_anisotropic',
    'EXT_texture_mirror_clamp_to_edge',
    'EXT_texture_norm16',
    'KHR_parallel_shader_compile',
    'NV_shader_noperspective_interpolation',
    'OES_draw_buffers_indexed',
    'OES_sample_variables',
    'OES_shader_multisample_interpolation',
    'OES_texture_float_linear',
    'WEBGL_clip_cull_distance',
    'WEBGL_compressed_texture_s3tc',
    'WEBGL_compressed_texture_s3tc_srgb',
    'WEBGL_debug_renderer_info',
    'WEBGL_debug_shaders',
    'WEBGL_lose_context',
    'WEBGL_multi_draw',
    'WEBGL_polygon_mode',
    'WEBGL_provoking_vertex',
    'WEBGL_stencil_texturing',
]

SHADER_PRECISION_D3D11 = {
    'vertex': {
        'highFloat': [127, 127, 23],
        'mediumFloat': [127, 127, 23],
        'lowFloat': [127, 127, 23],
        'highInt': [31, 30, 0],
        'mediumInt': [31, 30, 0],
        'lowInt': [31, 30, 0],
    },
    'fragment': {
        'highFloat': [127, 127, 23],
        'mediumFloat': [127, 127, 23],
        'lowFloat': [127, 127, 23],
        'highInt': [31, 30, 0],
        'mediumInt': [31, 30, 0],
        'lowInt': [31, 30, 0],
    },
}

WEBGPU_NVIDIA_AMPERE_D3D12 = WebGPUProfile(
    vendor='nvidia',
    architecture='ampere',
    device='',
    description='',
    limits={
        'maxTextureDimension1D': 16384,
        'maxTextureDimension2D': 16384,
        'maxTextureDimension3D': 2048,
        'maxTextureArrayLayers': 2048,
        'maxBindGroups': 4,
        'maxBindGroupsPlusVertexBuffers': 24,
        'maxBindingsPerBindGroup': 1000,
        'maxDynamicUniformBuffersPerPipelineLayout': 10,
        'maxDynamicStorageBuffersPerPipelineLayout': 8,
        'maxSampledTexturesPerShaderStage': 48,
        'maxSamplersPerShaderStage': 16,
        'maxStorageBuffersPerShaderStage': 16,
        'maxStorageTexturesPerShaderStage': 8,
        'maxUniformBuffersPerShaderStage': 12,
        'maxUniformBufferBindingSize': 65536,
        'maxStorageBufferBindingSize': 2147483644,
        'minUniformBufferOffsetAlignment': 256,
        'minStorageBufferOffsetAlignment': 256,
        'maxVertexBuffers': 8,
        'maxBufferSize': 2147483648,
        'maxVertexAttributes': 30,
        'maxVertexBufferArrayStride': 2048,
        'maxInterStageShaderVariables': 28,
        'maxColorAttachments': 8,
        'maxColorAttachmentBytesPerSample': 128,
        'maxComputeWorkgroupStorageSize': 32768,
        'maxComputeInvocationsPerWorkgroup': 1024,
        'maxComputeWorkgroupSizeX': 1024,
        'maxComputeWorkgroupSizeY': 1024,
        'maxComputeWorkgroupSizeZ': 64,
        'maxComputeWorkgroupsPerDimension': 65535,
        'maxStorageBuffersInVertexStage': 16,
        'maxStorageBuffersInFragmentStage': 16,
    },
    features=[
        'core-features-and-limits',
        'depth-clip-control',
        'depth32float-stencil8',
        'texture-compression-bc',
        'texture-compression-bc-sliced-3d',
        'timestamp-query',
        'indirect-first-instance',
        'shader-f16',
        'rg11b10ufloat-renderable',
        'bgra8unorm-storage',
        'float32-filterable',
        'float32-blendable',
        'clip-distances',
        'dual-source-blending',
        'subgroups',
        'texture-component-swizzle',
        'texture-formats-tier1',
        'texture-formats-tier2',
        'primitive-index',
        'subgroup-size-control',
    ],
)

WINDOWS_ABSENT_APIS = [
    'BarcodeDetector',
    'ContactsManager',
    'ContentIndex',
    'navigator.contacts',
    'NetworkInformation.downlinkMax',
]

WINDOWS_WEBGL = WebGLProfile(
    vendor='Google Inc. (NVIDIA)',
    renderer='ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002504) Direct3D11 vs_5_0 ps_5_0, D3D11)',
    max_texture_size=16384,
    max_renderbuffer_size=16384,
    max_viewport_dims=[32767, 32767],
    max_cube_map_texture_size=16384,
    max_3d_texture_size=2048,
    max_array_texture_layers=2048,
    max_vertex_attribs=16,
    max_vertex_uniform_vectors=4096,
    max_vertex_uniform_components=16384,
    max_fragment_uniform_vectors=1024,
    max_fragment_uniform_components=4096,
    max_varying_vectors=30,
    max_varying_components=120,
    max_vertex_output_components=120,
    max_fragment_input_components=120,
    max_texture_image_units=16,
    max_vertex_texture_image_units=16,
    max_combined_texture_image_units=32,
    max_color_attachments=8,
    max_draw_buffers=8,
    max_samples=8,
    max_uniform_block_size=65536,
    max_uniform_buffer_bindings=24,
    max_vertex_uniform_blocks=12,
    max_fragment_uniform_blocks=12,
    max_combined_uniform_blocks=24,
    max_combined_vertex_uniform_components=212992,
    max_combined_fragment_uniform_components=200704,
    uniform_buffer_offset_alignment=256,
    max_texture_lod_bias=2.0,
    max_transform_feedback_interleaved_components=120,
    aliased_line_width_range=[1, 1],
    aliased_point_size_range=[1, 1024],
    supported_extensions=DESKTOP_EXTENSIONS,
    webgl2_extensions=DESKTOP_WEBGL2_EXTENSIONS,
    shader_precision_formats=SHADER_PRECISION_D3D11,
)

# --- Linux 컨테이너 신원 (Docker 에서 실행할 때) --------------------------------
# pydoll examples/fingerprints.py 의 ``linux_container`` 를 서울 신원으로 고친 것.
# 컨테이너에는 GPU 가 없어 소프트웨어 렌더러로 드러나므로, 흔한 Intel 내장 그래픽으로 보고한다.

LINUX_WINDOW_WIDTH = 1920
LINUX_WINDOW_HEIGHT = 1053

LINUX_SCREEN = ScreenFingerprint(
    width=1920,
    height=1080,
    avail_width=1920,
    avail_height=1053,
    avail_top=27,
    avail_left=0,
    color_depth=24,
    pixel_depth=24,
    device_pixel_ratio=1.0,
    orientation_type='landscape-primary',
    orientation_angle=0,
)

LINUX_HARDWARE = HardwareFingerprint(hardware_concurrency=4, device_memory=8, max_touch_points=0)

# Dockerfile 이 설치하는 폰트와 정확히 맞춘다 (fonts-dejavu-core, fonts-liberation, fonts-noto-cjk).
LINUX_FONTS = FontFingerprint(
    available_fonts=[
        'DejaVu Sans',
        'DejaVu Sans Mono',
        'DejaVu Serif',
        'Liberation Mono',
        'Liberation Sans',
        'Liberation Serif',
        'Noto Sans CJK KR',
        'Noto Sans Mono CJK KR',
        'Noto Serif CJK KR',
    ]
)

LINUX_ABSENT_APIS = [
    'BarcodeDetector',
    'navigator.windowControlsOverlay',
    'DocumentPictureInPicture',
    'documentPictureInPicture',
]

SHADER_PRECISION_DESKTOP_GL = {
    'vertex': {
        'highFloat': [127, 127, 23],
        'mediumFloat': [127, 127, 23],
        'lowFloat': [127, 127, 23],
        'highInt': [31, 30, 0],
        'mediumInt': [31, 30, 0],
        'lowInt': [31, 30, 0],
    },
    'fragment': {
        'highFloat': [127, 127, 23],
        'mediumFloat': [127, 127, 23],
        'lowFloat': [127, 127, 23],
        'highInt': [31, 30, 0],
        'mediumInt': [31, 30, 0],
        'lowInt': [31, 30, 0],
    },
}

WEBGL_LINUX_MESA_INTEL = WebGLProfile(
    vendor='Google Inc. (Intel)',
    renderer='ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)',
    max_texture_size=16384,
    max_renderbuffer_size=16384,
    max_cube_map_texture_size=16384,
    max_viewport_dims=[16384, 16384],
    max_3d_texture_size=2048,
    max_array_texture_layers=2048,
    max_vertex_attribs=16,
    max_vertex_uniform_vectors=1024,
    max_fragment_uniform_vectors=1024,
    max_vertex_uniform_components=4096,
    max_fragment_uniform_components=4096,
    max_combined_vertex_uniform_components=249856,
    max_combined_fragment_uniform_components=249856,
    max_varying_vectors=32,
    max_varying_components=128,
    max_vertex_output_components=128,
    max_fragment_input_components=128,
    max_texture_image_units=32,
    max_vertex_texture_image_units=32,
    max_combined_texture_image_units=64,
    max_draw_buffers=8,
    max_color_attachments=8,
    max_samples=4,
    max_uniform_buffer_bindings=72,
    max_uniform_block_size=65536,
    max_vertex_uniform_blocks=15,
    max_fragment_uniform_blocks=15,
    max_combined_uniform_blocks=30,
    uniform_buffer_offset_alignment=16,
    max_texture_lod_bias=16.0,
    max_elements_vertices=3000,
    max_elements_indices=3000,
    max_transform_feedback_interleaved_components=4,
    max_transform_feedback_separate_components=4,
    max_transform_feedback_separate_attribs=64,
    subpixel_bits=4,
    aliased_point_size_range=[1, 256],
    aliased_line_width_range=[1, 255],
    supported_extensions=[
        'EXT_clip_control',
        'EXT_color_buffer_float',
        'EXT_color_buffer_half_float',
        'EXT_conservative_depth',
        'EXT_depth_clamp',
        'EXT_disjoint_timer_query_webgl2',
        'EXT_float_blend',
        'EXT_polygon_offset_clamp',
        'EXT_render_snorm',
        'EXT_texture_compression_bptc',
        'EXT_texture_compression_rgtc',
        'EXT_texture_filter_anisotropic',
        'EXT_texture_mirror_clamp_to_edge',
        'EXT_texture_norm16',
        'KHR_parallel_shader_compile',
        'NV_shader_noperspective_interpolation',
        'OES_draw_buffers_indexed',
        'OES_sample_variables',
        'OES_shader_multisample_interpolation',
        'OES_texture_float_linear',
        'OVR_multiview2',
        'WEBGL_blend_func_extended',
        'WEBGL_clip_cull_distance',
        'WEBGL_compressed_texture_s3tc',
        'WEBGL_compressed_texture_s3tc_srgb',
        'WEBGL_debug_renderer_info',
        'WEBGL_debug_shaders',
        'WEBGL_lose_context',
        'WEBGL_multi_draw',
        'WEBGL_polygon_mode',
        'WEBGL_provoking_vertex',
        'WEBGL_stencil_texturing',
    ],
    shader_precision_formats=SHADER_PRECISION_DESKTOP_GL,
)

# --- 프로필 조립 ---------------------------------------------------------------


def build_macos_seoul_profile(chrome_version: str) -> FingerprintConfig:
    """macOS Apple Silicon + 서울 신원의 전체 프로필을 만든다.

    Args:
        chrome_version: 실제로 띄운 Chrome 의 전체 버전 (예: '158.0.8127.38').
            ``browser.get_version()`` 의 ``product`` 값에서 얻는다.
            navigator.userAgent 에는 pydoll 이 메이저만 남긴 축약형(158.0.0.0)을 노출하고,
            전체 빌드는 Sec-CH-UA-Full-Version-List 에만 들어간다.
    """
    # Chrome 은 Apple Silicon 에서도 UA 에 'Intel Mac OS X 10_15_7' 을 고정으로 쓴다.
    # 실제 아키텍처(arm)는 Client Hints 로만 전달된다.
    user_agent = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        f'Chrome/{chrome_version} Safari/537.36'
    )
    return FingerprintConfig(
        user_agent=user_agent,
        client_hints=ClientHintsFingerprint(
            platform_version='15.6.1',
            architecture='arm',
            bitness='64',
        ),
        navigator=NavigatorFingerprint(
            platform='MacIntel',
            vendor='Google Inc.',
            app_version=user_agent[len('Mozilla/') :],
            pdf_viewer_enabled=True,
        ),
        webgl=WEBGL,
        webgpu=WEBGPU_APPLE_M_SERIES,
        screen=SCREEN,
        hardware=HARDWARE,
        geolocation=GEOLOCATION,
        timezone=TIMEZONE,
        locale=LOCALE,
        media_devices=MediaDevicesFingerprint(audio_inputs=1, audio_outputs=2, video_inputs=1),
        media_codecs=DESKTOP_CHROMIUM_CODECS,
        audio=AudioFingerprint(sample_rate=44100, max_channel_count=2),
        speech=SPEECH,
        network_connection=DESKTOP_NETWORK,
        fonts=FONTS,
        platform_apis=PlatformApisFingerprint(hidden=MACOS_ABSENT_APIS),
        media_features=MediaFeaturesFingerprint(color_gamut='p3'),
        permissions=DESKTOP_PERMISSIONS,
    )


def build_minimal_profile() -> FingerprintConfig:
    """언어·시간대만 맞추는 최소 프로필. 나머지는 실제 브라우저 값을 그대로 쓴다."""
    return FingerprintConfig(locale=LOCALE, timezone=TIMEZONE)


def windows_platform_version() -> str:
    """Sec-CH-UA-Platform-Version 값. Windows 11 은 '15.0.0', Windows 10 은 '10.0.0'."""
    try:
        build = int(platform.version().split('.')[-1])
    except ValueError:
        return '15.0.0'
    return '15.0.0' if build >= 22000 else '10.0.0'


def build_windows_seoul_profile(chrome_version: str) -> FingerprintConfig:
    """Windows 데스크톱 + 서울 신원의 전체 프로필. Windows 에서 실행할 때 쓴다."""
    user_agent = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        f'Chrome/{chrome_version} Safari/537.36'
    )
    return FingerprintConfig(
        user_agent=user_agent,
        client_hints=ClientHintsFingerprint(
            platform_version=windows_platform_version(),
            architecture='x86',
            bitness='64',
        ),
        navigator=NavigatorFingerprint(
            platform='Win32',
            vendor='Google Inc.',
            app_version=user_agent[len('Mozilla/') :],
            pdf_viewer_enabled=True,
        ),
        webgl=WINDOWS_WEBGL,
        webgpu=WEBGPU_NVIDIA_AMPERE_D3D12,
        screen=WINDOWS_SCREEN,
        hardware=WINDOWS_HARDWARE,
        geolocation=GEOLOCATION,
        timezone=TIMEZONE,
        locale=LOCALE,
        media_devices=MediaDevicesFingerprint(audio_inputs=1, audio_outputs=1, video_inputs=1),
        media_codecs=DESKTOP_CHROMIUM_CODECS,
        audio=AudioFingerprint(sample_rate=48000, max_channel_count=2),
        speech=WINDOWS_SPEECH,
        network_connection=DESKTOP_NETWORK,
        fonts=WINDOWS_FONTS,
        platform_apis=PlatformApisFingerprint(hidden=WINDOWS_ABSENT_APIS),
        media_features=MediaFeaturesFingerprint(color_gamut='srgb'),
        permissions=DESKTOP_PERMISSIONS,
    )


def build_full_profile(chrome_version: str) -> FingerprintConfig:
    """실행 중인 OS 에 맞는 전체 프로필. OS 계층은 위장할 수 없으므로 프로필도 같은 OS 여야 한다.

    그 밖의 OS 에서는 최소 프로필(언어·시간대만)을 쓴다.
    """
    if sys.platform == 'darwin':
        return build_macos_seoul_profile(chrome_version)
    if sys.platform == 'win32':
        return build_windows_seoul_profile(chrome_version)
    if sys.platform.startswith('linux'):
        return build_linux_seoul_profile(chrome_version)
    return build_minimal_profile()


def window_size() -> tuple[int, int]:
    """실행 중인 OS 의 프로필에 맞는 창 크기 (--window-size)."""
    if sys.platform == 'win32':
        return WINDOWS_WINDOW_WIDTH, WINDOWS_WINDOW_HEIGHT
    if sys.platform.startswith('linux'):
        return LINUX_WINDOW_WIDTH, LINUX_WINDOW_HEIGHT
    return WINDOW_WIDTH, WINDOW_HEIGHT


def build_linux_seoul_profile(chrome_version: str) -> FingerprintConfig:
    """Linux 데스크톱 + 서울 신원의 전체 프로필. Docker 컨테이너에서 실행할 때 쓴다."""
    # Chrome 은 ARM Linux 에서도 UA 에 'X11; Linux x86_64' 를 고정으로 쓴다.
    user_agent = (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
        f'Chrome/{chrome_version} Safari/537.36'
    )
    return FingerprintConfig(
        user_agent=user_agent,
        client_hints=ClientHintsFingerprint(
            platform_version='',
            architecture='x86',
            bitness='64',
            model='',
            form_factors=['Desktop'],
        ),
        navigator=NavigatorFingerprint(
            platform='Linux x86_64',
            vendor='Google Inc.',
            app_version=user_agent[len('Mozilla/') :],
            pdf_viewer_enabled=True,
        ),
        webgl=WEBGL_LINUX_MESA_INTEL,
        screen=LINUX_SCREEN,
        hardware=LINUX_HARDWARE,
        geolocation=GEOLOCATION,
        timezone=TIMEZONE,
        locale=LOCALE,
        media_devices=MediaDevicesFingerprint(audio_inputs=1, audio_outputs=1, video_inputs=0),
        media_codecs=DESKTOP_CHROMIUM_CODECS,
        audio=AudioFingerprint(sample_rate=48000, max_channel_count=2),
        network_connection=DESKTOP_NETWORK,
        fonts=LINUX_FONTS,
        platform_apis=PlatformApisFingerprint(hidden=LINUX_ABSENT_APIS),
        media_features=MediaFeaturesFingerprint(color_gamut='srgb'),
        permissions=DESKTOP_PERMISSIONS,
    )
