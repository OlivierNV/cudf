/*
 * Copyright (c) 2018, NVIDIA CORPORATION.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
	 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#pragma once

#include <vector>
#include <string>

#include "cudf.h"

enum {
    IO_UNCOMP_STREAM_TYPE_INFER = 0,
    IO_UNCOMP_STREAM_TYPE_GZIP  = 1,
    IO_UNCOMP_STREAM_TYPE_ZIP   = 2,
    IO_UNCOMP_STREAM_TYPE_BZIP2 = 3,
    IO_UNCOMP_STREAM_TYPE_XZ    = 4,
};

gdf_error io_uncompress_single_h2d(const void *src, gdf_size_type src_size, int strm_type, std::vector<char>& dst);

gdf_error getUncompressedHostData(const char* h_data, size_t num_bytes,
    const std::string& compression, std::vector<char>& h_uncomp_data);
